#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE = Path(__file__).with_name("comparator_closure_scan.py")
SPEC = importlib.util.spec_from_file_location("comparator_closure_scan", MODULE)
assert SPEC and SPEC.loader
SCAN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SCAN
SPEC.loader.exec_module(SCAN)


class StripAndImportTests(unittest.TestCase):
    def test_unicode_import_is_preserved(self) -> None:
        source = "import OAI.Analysis.MatrixSigning.Arithmetic.Kappa₁\n"
        self.assertEqual(SCAN.parse_imports(source), ["OAI.Analysis.MatrixSigning.Arithmetic.Kappa₁"])

    def test_comments_and_strings_do_not_create_imports(self) -> None:
        source = '-- import OAI.Bad\ndef s := "import OAI.Worse"\nimport OAI.Good\n'
        clean = SCAN.strip_lean_comments_and_strings(source)
        self.assertEqual(SCAN.parse_imports(clean), ["OAI.Good"])
        self.assertEqual(len(source), len(clean))
        self.assertEqual(source.count("\n"), clean.count("\n"))

    def test_nested_comments_and_raw_strings(self) -> None:
        source = '/- outer /- import OAI.Bad -/ -/\ndef s := r##"import OAI.Worse"##\nimport OAI.Good\n'
        clean = SCAN.strip_lean_comments_and_strings(source)
        self.assertEqual(SCAN.parse_imports(clean), ["OAI.Good"])


class DeclarationTests(unittest.TestCase):
    def test_namespace_reconstruction(self) -> None:
        source = """namespace OAI
namespace SiegelZeros
section
namespace WeightedTorusJets
@[simp] theorem exists_absolute_real_zero_gap : True := by trivial
end WeightedTorusJets
end
end SiegelZeros
end OAI
"""
        declarations = SCAN.parse_declarations(
            source,
            module="OAI.NumberTheory.SiegelZeros.Main",
            path="lean/OAI/NumberTheory/SiegelZeros/Main.lean",
            relevant_short_names={"exists_absolute_real_zero_gap"},
        )
        self.assertEqual(len(declarations), 1)
        self.assertEqual(
            declarations[0].full_name,
            "OAI.SiegelZeros.WeightedTorusJets.exists_absolute_real_zero_gap",
        )
        self.assertEqual(declarations[0].kind, "theorem")

    def test_dotted_relative_declaration(self) -> None:
        source = """namespace OAI
namespace SiegelZeros
 theorem WeightedTorusJets.dirichletRealZeroBound_proof : True := by trivial
end SiegelZeros
end OAI
"""
        declarations = SCAN.parse_declarations(
            source,
            module="M",
            path="M.lean",
            relevant_short_names={"dirichletRealZeroBound_proof"},
        )
        self.assertEqual(
            declarations[0].full_name,
            "OAI.SiegelZeros.WeightedTorusJets.dirichletRealZeroBound_proof",
        )

    def test_root_qualified_declaration(self) -> None:
        source = "namespace A\ntheorem _root_.B.t : True := by trivial\nend A\n"
        declarations = SCAN.parse_declarations(
            source,
            module="M",
            path="M.lean",
            relevant_short_names={"t"},
        )
        self.assertEqual(declarations[0].full_name, "B.t")


class ClosureAndResolutionTests(unittest.TestCase):
    def decl(self, full: str, module: str, kind: str = "theorem") -> object:
        return SCAN.Declaration(full, full.split(".")[-1], full.split(".")[-1], kind, module, module + ".lean", 1)

    def test_cycle_closure_is_finite(self) -> None:
        edges = {"A": ("B",), "B": ("A", "C"), "C": ()}
        self.assertEqual(SCAN.compute_closure("A", edges, set(edges)), {"A", "B", "C"})

    def test_exact_target_in_imported_module_resolves(self) -> None:
        d = self.decl("OAI.X.target", "OAI.X.Provider")
        result = SCAN.classify_target(
            config="X.json",
            target="OAI.X.target",
            expected_role="theorem",
            solution_module="OAI.X.Main",
            closure={"OAI.X.Main", "OAI.X.Provider"},
            full_index={d.full_name: [d]},
            short_index={d.short_name: [d]},
        )
        self.assertEqual(result.status, "EXACT_IN_SOLUTION_CLOSURE")
        self.assertEqual(result.severity, "none")

    def test_exact_target_outside_closure_is_critical(self) -> None:
        d = self.decl("OAI.X.target", "OAI.X.Unrelated")
        result = SCAN.classify_target(
            config="X.json",
            target="OAI.X.target",
            expected_role="theorem",
            solution_module="OAI.X.Main",
            closure={"OAI.X.Main"},
            full_index={d.full_name: [d]},
            short_index={d.short_name: [d]},
        )
        self.assertEqual(result.status, "EXACT_DECLARATION_OUTSIDE_SOLUTION_CLOSURE")
        self.assertEqual(result.severity, "critical")

    def test_role_mismatch_is_visible(self) -> None:
        d = self.decl("OAI.X.target", "OAI.X.Main", kind="def")
        result = SCAN.classify_target(
            config="X.json",
            target="OAI.X.target",
            expected_role="theorem",
            solution_module="OAI.X.Main",
            closure={"OAI.X.Main"},
            full_index={d.full_name: [d]},
            short_index={d.short_name: [d]},
        )
        self.assertEqual(result.status, "EXACT_NAME_ROLE_MISMATCH")
        self.assertEqual(result.severity, "high")

    def test_short_only_match_is_not_promoted_to_exact(self) -> None:
        d = self.decl("OAI.Other.target", "OAI.X.Main")
        result = SCAN.classify_target(
            config="X.json",
            target="OAI.X.target",
            expected_role="theorem",
            solution_module="OAI.X.Main",
            closure={"OAI.X.Main"},
            full_index={d.full_name: [d]},
            short_index={d.short_name: [d]},
        )
        self.assertEqual(result.status, "UNIQUE_SHORT_NAME_IN_CLOSURE")
        self.assertEqual(result.severity, "medium")


if __name__ == "__main__":
    unittest.main(verbosity=2)
