#!/usr/bin/env python3
"""Hostile tests for run_theorem_kernel_probe.py."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("run_theorem_kernel_probe.py")
SPEC = importlib.util.spec_from_file_location("run_theorem_kernel_probe", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
PROBE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROBE
SPEC.loader.exec_module(PROBE)


class AxiomParserTests(unittest.TestCase):
    def test_standard_axiom_output(self) -> None:
        output = (
            "OAI.theorem : True\n"
            "'OAI.theorem' depends on axioms: "
            "[propext, Classical.choice, Quot.sound]\n"
        )
        axioms, error = PROBE.parse_axioms(output)
        self.assertIsNone(error)
        self.assertEqual(
            axioms, ["Classical.choice", "Quot.sound", "propext"]
        )

    def test_no_axioms_is_accepted_as_empty_list(self) -> None:
        axioms, error = PROBE.parse_axioms(
            "'OAI.constructive' depends on axioms: []\n"
        )
        self.assertIsNone(error)
        self.assertEqual(axioms, [])

    def test_missing_axiom_output_is_not_silently_accepted(self) -> None:
        axioms, error = PROBE.parse_axioms("theorem output only\n")
        self.assertIsNone(axioms)
        self.assertIn("found 0", error or "")

    def test_multiple_axiom_outputs_are_ambiguous(self) -> None:
        output = (
            "'A' depends on axioms: [propext]\n"
            "'B' depends on axioms: [Quot.sound]\n"
        )
        axioms, error = PROBE.parse_axioms(output)
        self.assertIsNone(axioms)
        self.assertIn("found 2", error or "")


class StablePolicyTests(unittest.TestCase):
    def test_axiom_allowlist_is_narrow(self) -> None:
        self.assertEqual(
            PROBE.ALLOWED_AXIOMS,
            {"propext", "Classical.choice", "Quot.sound"},
        )

    def test_skipped_phase_cannot_look_successful(self) -> None:
        result = PROBE.skipped("build", "update failed")
        self.assertIsNone(result["exit_code"])
        self.assertEqual(result["status"], "SKIPPED")
        self.assertEqual(result["reason"], "update failed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
