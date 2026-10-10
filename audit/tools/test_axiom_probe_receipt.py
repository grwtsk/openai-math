#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE = Path(__file__).with_name("axiom_probe_receipt.py")
SPEC = importlib.util.spec_from_file_location("axiom_probe_receipt", MODULE)
assert SPEC and SPEC.loader
PROBE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROBE
SPEC.loader.exec_module(PROBE)


class ParserTests(unittest.TestCase):
    def block(self, target: str, body: str) -> str:
        return f"AUDIT_TARGET_BEGIN|{target}\n{body}\nAUDIT_TARGET_END|{target}\n"

    def test_multiline_axioms(self) -> None:
        target = PROBE.TARGETS[0]
        text = self.block(target, "type output\n't' depends on axioms: [propext,\n Classical.choice, Quot.sound]")
        blocks = PROBE.extract_blocks(text)
        self.assertEqual(PROBE.parse_axioms(blocks[target]), ["Classical.choice", "Quot.sound", "propext"])

    def test_no_axioms(self) -> None:
        self.assertEqual(PROBE.parse_axioms("'t' does not depend on any axioms"), [])

    def test_duplicate_block_rejected(self) -> None:
        target = PROBE.TARGETS[0]
        with self.assertRaises(ValueError):
            PROBE.extract_blocks(self.block(target, "x") + self.block(target, "y"))

    def test_unauthorized_axiom_is_violation(self) -> None:
        text = "".join(
            self.block(target, f"{target} : Prop\n'{target}' depends on axioms: [propext, sorryAx]")
            for target in PROBE.TARGETS
        )
        report, violations = PROBE.make_report(text, {})
        self.assertEqual(len(report["targets"]), len(PROBE.TARGETS))
        self.assertTrue(any(v["code"] == "UNAUTHORIZED_TRANSITIVE_AXIOM" for v in violations))

    def test_missing_target_is_violation(self) -> None:
        target = PROBE.TARGETS[0]
        text = self.block(target, f"'{target}' depends on axioms: [propext]")
        _report, violations = PROBE.make_report(text, {})
        self.assertTrue(any(v["code"] == "MISSING_TARGET_BLOCK" for v in violations))

    def test_permitted_profile_passes(self) -> None:
        text = "".join(
            self.block(target, f"{target} : Prop\n'{target}' depends on axioms: [propext, Classical.choice, Quot.sound]")
            for target in PROBE.TARGETS
        )
        report, violations = PROBE.make_report(text, {})
        self.assertEqual(violations, [])
        self.assertEqual(len(report["targets"]), 2)

    def test_changed_lean_subtree_is_violation(self) -> None:
        text = "".join(
            self.block(target, f"{target} : Prop\n'{target}' depends on axioms: [propext]")
            for target in PROBE.TARGETS
        )
        _report, violations = PROBE.make_report(
            text,
            {
                "lean_subtree_matches_frozen_base": False,
                "audit_lean_tree": "audit",
                "frozen_lean_tree": "frozen",
            },
        )
        self.assertTrue(any(v["code"] == "LEAN_SUBTREE_DIFFERS_FROM_FROZEN_BASE" for v in violations))


if __name__ == "__main__":
    unittest.main(verbosity=2)
