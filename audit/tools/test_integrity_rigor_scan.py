#!/usr/bin/env python3
"""Hostile, dependency-free tests for the static integrity scanner."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("integrity_rigor_scan.py")
SPEC = importlib.util.spec_from_file_location("integrity_rigor_scan", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
SCAN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SCAN
SPEC.loader.exec_module(SCAN)


class StripLeanCommentsAndStringsTests(unittest.TestCase):
    def assert_shape_preserved(self, source: str, stripped: str) -> None:
        self.assertEqual(len(source), len(stripped))
        self.assertEqual(source.count("\n"), stripped.count("\n"))

    def test_line_comment_hides_tokens(self) -> None:
        source = "theorem good : True := by trivial -- sorry axiom unsafe\n#check good\n"
        stripped = SCAN.strip_lean_comments_and_strings(source)
        self.assert_shape_preserved(source, stripped)
        self.assertNotIn("sorry", stripped)
        self.assertNotIn("axiom", stripped)
        self.assertIn("theorem good", stripped)
        self.assertIn("#check good", stripped)

    def test_nested_block_comments_hide_tokens(self) -> None:
        source = "before /- outer sorry /- inner axiom -/ unsafe -/ after\n"
        stripped = SCAN.strip_lean_comments_and_strings(source)
        self.assert_shape_preserved(source, stripped)
        self.assertNotIn("sorry", stripped)
        self.assertNotIn("axiom", stripped)
        self.assertNotIn("unsafe", stripped)
        self.assertRegex(stripped.strip(), r"^before +after$")

    def test_ordinary_string_hides_tokens_and_preserves_escaped_quote(self) -> None:
        source = 'def s := "sorry \\" axiom"\ntheorem t : True := by trivial\n'
        stripped = SCAN.strip_lean_comments_and_strings(source)
        self.assert_shape_preserved(source, stripped)
        self.assertNotIn("sorry", stripped)
        self.assertNotIn("axiom", stripped)
        self.assertIn("theorem t", stripped)

    def test_raw_string_hides_tokens(self) -> None:
        source = 'def s := r##"sorry axiom \\" nested"##\ntheorem t : True := by trivial\n'
        stripped = SCAN.strip_lean_comments_and_strings(source)
        self.assert_shape_preserved(source, stripped)
        self.assertNotIn("sorry", stripped)
        self.assertNotIn("axiom", stripped)
        self.assertIn("theorem t", stripped)

    def test_tokens_outside_comments_remain(self) -> None:
        source = "axiom A : Prop\ntheorem t : A := by sorry\n"
        stripped = SCAN.strip_lean_comments_and_strings(source)
        self.assert_shape_preserved(source, stripped)
        self.assertIn("axiom A", stripped)
        self.assertIn("sorry", stripped)

    def test_multiline_comment_preserves_exact_line_numbers(self) -> None:
        source = "line1\n/- sorry\naxiom\n-/\nrun_tac foo\n"
        stripped = SCAN.strip_lean_comments_and_strings(source)
        self.assertEqual(SCAN.line_for_offset(stripped, stripped.index("run_tac")), 5)


class SourceIdentityTests(unittest.TestCase):
    def test_module_to_path_for_root_and_nested_modules(self) -> None:
        self.assertEqual(SCAN.module_to_path("OAI"), SCAN.LEAN_ROOT / "OAI.lean")
        self.assertEqual(
            SCAN.module_to_path("OAI.NumberTheory.DirichletL.Nonvanishing"),
            SCAN.LEAN_ROOT / "OAI/NumberTheory/DirichletL/Nonvanishing.lean",
        )

    def test_frozen_revision_is_full_sha(self) -> None:
        self.assertRegex(SCAN.BASE_REV, r"^[0-9a-f]{40}$")

    def test_approved_axiom_profile_is_narrow(self) -> None:
        self.assertEqual(
            SCAN.APPROVED_FOUNDATIONAL_AXIOMS,
            {"propext", "Quot.sound", "Classical.choice"},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
