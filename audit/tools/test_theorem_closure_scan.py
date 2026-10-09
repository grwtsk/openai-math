#!/usr/bin/env python3
"""Hostile dependency-free tests for theorem_closure_scan.py."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("theorem_closure_scan.py")
SPEC = importlib.util.spec_from_file_location("theorem_closure_scan", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
SCAN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SCAN
SPEC.loader.exec_module(SCAN)


class LeanLexingTests(unittest.TestCase):
    def assert_shape_preserved(self, source: str, stripped: str) -> None:
        self.assertEqual(len(source), len(stripped))
        self.assertEqual(source.count("\n"), stripped.count("\n"))

    def test_nested_comments_and_strings_hide_trust_tokens(self) -> None:
        source = (
            'theorem good : True := by trivial\n'
            '/- sorry /- axiom Hidden : Prop -/ admit -/\n'
            'def s := r##"sorry axiom admit"##\n'
            '-- sorry\n'
        )
        stripped = SCAN.strip_lean_comments_and_strings(source)
        self.assert_shape_preserved(source, stripped)
        self.assertNotIn("sorry", stripped)
        self.assertNotIn("axiom Hidden", stripped)
        self.assertNotIn("admit", stripped)
        self.assertIn("theorem good", stripped)

    def test_import_parser_supports_multiple_and_public_imports(self) -> None:
        source = (
            "import OAI.A OAI.B\n"
            "public import OAI.Kappa₁\n"
            "private import Mathlib.Data.Nat.Basic\n"
        )
        imports, unparsed = SCAN.parse_imports(source)
        self.assertEqual(
            imports,
            [
                "OAI.A",
                "OAI.B",
                "OAI.Kappa₁",
                "Mathlib.Data.Nat.Basic",
            ],
        )
        self.assertEqual(unparsed, [])

    def test_empty_import_is_retained_for_review(self) -> None:
        imports, unparsed = SCAN.parse_imports("import\n")
        self.assertEqual(imports, [])
        self.assertEqual(unparsed, [1])


class ModuleResolutionTests(unittest.TestCase):
    def test_unicode_module_identity_is_preserved(self) -> None:
        root = Path("/tmp/lean")
        self.assertEqual(
            SCAN.module_to_path(
                "OAI.Analysis.MatrixSigning.Arithmetic.Kappa₁", root
            ),
            root
            / "OAI/Analysis/MatrixSigning/Arithmetic/Kappa₁.lean",
        )

    def test_internal_module_classification(self) -> None:
        self.assertTrue(SCAN.is_internal_module("OAI"))
        self.assertTrue(SCAN.is_internal_module("OAI.NumberTheory.X"))
        self.assertTrue(
            SCAN.is_internal_module("ComparatorChallenges.SiegelZeros")
        )
        self.assertFalse(SCAN.is_internal_module("Mathlib.Analysis.Basic"))

    def test_bounded_closure_walk(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lean = Path(td) / "lean"
            (lean / "OAI").mkdir(parents=True)
            (lean / "OAI/A.lean").write_text(
                "import OAI.B Mathlib\n", encoding="utf-8"
            )
            (lean / "OAI/B.lean").write_text(
                "public import OAI.Kappa₁\n", encoding="utf-8"
            )
            (lean / "OAI/Kappa₁.lean").write_text(
                "theorem kappa : True := by trivial\n", encoding="utf-8"
            )
            closure = SCAN.collect_closure("OAI.A", lean_root=lean)
            self.assertEqual(
                closure["modules"], ["OAI.A", "OAI.B", "OAI.Kappa₁"]
            )
            self.assertEqual(closure["external_imports"], ["Mathlib"])
            self.assertEqual(closure["missing_internal_imports"], [])

    def test_missing_internal_import_is_not_externalized(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lean = Path(td) / "lean"
            (lean / "OAI").mkdir(parents=True)
            (lean / "OAI/A.lean").write_text(
                "import OAI.DoesNotExist\n", encoding="utf-8"
            )
            closure = SCAN.collect_closure("OAI.A", lean_root=lean)
            self.assertEqual(closure["external_imports"], [])
            self.assertEqual(
                closure["missing_internal_imports"],
                [{"source": "OAI.A", "module": "OAI.DoesNotExist"}],
            )


class SourcePolicyTests(unittest.TestCase):
    def categories(self, findings):
        return {finding.category for finding in findings}

    def test_comment_hidden_sorry_is_not_a_finding(self) -> None:
        raw = (
            "-- sorry\n"
            "theorem good : True := by\n"
            "  exact True.intro\n"
        )
        findings, _ = SCAN.scan_source(
            module="OAI.Good",
            path=Path("/tmp/Good.lean"),
            raw=raw,
            imports=[],
        )
        self.assertNotIn("sorry_token", self.categories(findings))

    def test_axiom_and_contradiction_are_distinguished(self) -> None:
        raw = (
            "axiom A : Prop\n"
            "theorem bad : False := by\n"
            "  exact False.elim (by contradiction)\n"
        )
        findings, _ = SCAN.scan_source(
            module="OAI.Bad",
            path=Path("/tmp/Bad.lean"),
            raw=raw,
            imports=[],
        )
        categories = self.categories(findings)
        self.assertIn("axiom_declaration", categories)
        self.assertIn("False.elim", categories)
        self.assertTrue(
            any(
                finding.category == "axiom_declaration"
                and finding.severity == "critical"
                for finding in findings
            )
        )
        self.assertTrue(
            any(
                finding.category == "False.elim"
                and finding.severity == "review"
                for finding in findings
            )
        )

    def test_solution_importing_challenge_is_critical(self) -> None:
        findings, _ = SCAN.scan_source(
            module="OAI.BadBoundary",
            path=Path("/tmp/BadBoundary.lean"),
            raw="import ComparatorChallenges.Fake\n",
            imports=["ComparatorChallenges.Fake"],
        )
        self.assertTrue(
            any(
                finding.category == "challenge_imported_by_solution"
                and finding.severity == "critical"
                for finding in findings
            )
        )

    def test_ordinary_opaque_is_review_not_axiom(self) -> None:
        raw = "opaque packaged : {n : Nat // n = 3} := ⟨3, rfl⟩\n"
        findings, _ = SCAN.scan_source(
            module="OAI.Packaged",
            path=Path("/tmp/Packaged.lean"),
            raw=raw,
            imports=[],
        )
        categories = self.categories(findings)
        self.assertIn("opaque_declaration", categories)
        self.assertNotIn("axiom_declaration", categories)
        self.assertTrue(
            any(
                finding.category == "opaque_declaration"
                and finding.severity == "review"
                for finding in findings
            )
        )


class StablePolicyTests(unittest.TestCase):
    def test_base_revision_is_full_sha(self) -> None:
        self.assertRegex(SCAN.BASE_REV, r"^[0-9a-f]{40}$")

    def test_target_keys_are_unique(self) -> None:
        keys = [target.key for target in SCAN.TARGETS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_critical_axiom_profile_is_narrow(self) -> None:
        self.assertEqual(
            SCAN.APPROVED_FOUNDATIONAL_AXIOMS,
            {"propext", "Quot.sound", "Classical.choice"},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
