#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).with_name("siegel_route_independence.py")
SPEC = importlib.util.spec_from_file_location("siegel_route_independence", MODULE)
assert SPEC and SPEC.loader
SCAN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SCAN
SPEC.loader.exec_module(SCAN)


class LexerTests(unittest.TestCase):
    def test_comments_strings_and_raw_strings_do_not_create_imports(self) -> None:
        source = (
            '-- import OAI.Bad\n'
            '/- import OAI.Worse /- import OAI.Nested -/ -/\n'
            'def s := "import OAI.String"\n'
            'def r := r##"import OAI.Raw"##\n'
            'import OAI.Good\n'
        )
        clean = SCAN.strip_lean_comments_and_strings(source)
        self.assertEqual(SCAN.parse_imports(clean), ["OAI.Good"])
        self.assertEqual(len(source), len(clean))
        self.assertEqual(source.count("\n"), clean.count("\n"))

    def test_unicode_import_is_preserved(self) -> None:
        self.assertEqual(
            SCAN.parse_imports("import OAI.Analysis.MatrixSigning.Arithmetic.Kappa₁\n"),
            ["OAI.Analysis.MatrixSigning.Arithmetic.Kappa₁"],
        )


class DeclarationTests(unittest.TestCase):
    def test_nested_namespace_target(self) -> None:
        source = """namespace OAI
namespace SiegelZeros
section
namespace WeightedTorusJets
theorem exists_absolute_real_zero_gap : True := by trivial
end WeightedTorusJets
end
end SiegelZeros
end OAI
"""
        declarations = SCAN.parse_declarations(source, module="M", path="M.lean")
        self.assertIn(
            "OAI.SiegelZeros.WeightedTorusJets.exists_absolute_real_zero_gap",
            {declaration.full_name for declaration in declarations},
        )

    def test_dotted_declaration_target(self) -> None:
        source = """namespace OAI
namespace SiegelZeros
theorem WeightedTorusJets.dirichletRealZeroBound_proof : True := by trivial
end SiegelZeros
end OAI
"""
        declarations = SCAN.parse_declarations(source, module="M", path="M.lean")
        self.assertIn(
            "OAI.SiegelZeros.WeightedTorusJets.dirichletRealZeroBound_proof",
            {declaration.full_name for declaration in declarations},
        )


class ClosureTests(unittest.TestCase):
    def write_module(self, root: Path, module: str, source: str) -> None:
        path = SCAN.module_to_path(module, root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    def test_separate_closures_remain_separate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_module(root, "OAI.Geometric", "import OAI.Shared\nnamespace OAI\ntheorem g : True := by trivial\nend OAI\n")
            self.write_module(root, "OAI.Analytic", "import OAI.Shared\nnamespace OAI\ntheorem a : True := by trivial\nend OAI\n")
            self.write_module(root, "OAI.Shared", "namespace OAI\ndef shared := 1\nend OAI\n")
            geometric = SCAN.crawl_closure("OAI.Geometric", root)
            analytic = SCAN.crawl_closure("OAI.Analytic", root)
            self.assertEqual(set(geometric["modules"]), {"OAI.Geometric", "OAI.Shared"})
            self.assertEqual(set(analytic["modules"]), {"OAI.Analytic", "OAI.Shared"})
            self.assertNotIn("OAI.Analytic", geometric["modules"])
            self.assertNotIn("OAI.Geometric", analytic["modules"])

    def test_cross_import_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_module(root, "OAI.Geometric", "import OAI.Analytic\n")
            self.write_module(root, "OAI.Analytic", "")
            geometric = SCAN.crawl_closure("OAI.Geometric", root)
            self.assertIn("OAI.Analytic", geometric["modules"])

    def test_unresolved_internal_import_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_module(root, "OAI.Root", "import OAI.Missing\n")
            closure = SCAN.crawl_closure("OAI.Root", root)
            self.assertEqual(closure["unresolved_internal_imports"], {"OAI.Missing"})

    def test_external_import_is_not_treated_as_missing_internal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_module(root, "OAI.Root", "import Mathlib\nimport PrimeNumberTheoremAnd.SiegelZeros.HadamardSupport\n")
            closure = SCAN.crawl_closure("OAI.Root", root)
            self.assertEqual(closure["unresolved_internal_imports"], set())
            self.assertIn("Mathlib", closure["external_imports"])
            self.assertIn("PrimeNumberTheoremAnd.SiegelZeros.HadamardSupport", closure["external_imports"])

    def test_closure_digest_is_order_independent(self) -> None:
        modules_a = {
            "A": {"path": "A.lean", "sha256": "1"},
            "B": {"path": "B.lean", "sha256": "2"},
        }
        modules_b = {
            "B": {"path": "B.lean", "sha256": "2"},
            "A": {"path": "A.lean", "sha256": "1"},
        }
        self.assertEqual(SCAN.closure_digest(modules_a), SCAN.closure_digest(modules_b))


if __name__ == "__main__":
    unittest.main(verbosity=2)
