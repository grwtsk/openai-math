#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE = Path(__file__).with_name("kaplansky_probe_receipt.py")
SPEC = importlib.util.spec_from_file_location("kaplansky_probe_receipt", MODULE)
assert SPEC and SPEC.loader
PROBE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROBE
SPEC.loader.exec_module(PROBE)


class KaplanskyReceiptTests(unittest.TestCase):
    def block(self, target: str, axioms: str = "propext, Classical.choice, Quot.sound") -> str:
        return (
            f"AUDIT_TARGET_BEGIN|{target}\n"
            f"{target} : Prop\n"
            f"'{target}' depends on axioms: [{axioms}]\n"
            f"AUDIT_TARGET_END|{target}\n"
        )

    def complete_log(self, axioms: str = "propext, Classical.choice, Quot.sound") -> str:
        targets = "".join(self.block(target, axioms) for target in PROBE.TARGETS)
        witness = (
            "AUDIT_WITNESS_BEGIN|source-parameters\n"
            + "\n".join(f"{token} : MockType" for token in PROBE.REQUIRED_WITNESS_TOKENS)
            + "\nAUDIT_WITNESS_END|source-parameters\n"
        )
        return targets + witness

    def test_permitted_profile_passes(self) -> None:
        report, violations = PROBE.make_report(self.complete_log(), {})
        self.assertEqual(violations, [])
        self.assertEqual(report["resolved_target_count"], len(PROBE.TARGETS))

    def test_sorryax_is_rejected(self) -> None:
        _report, violations = PROBE.make_report(
            self.complete_log("propext, Classical.choice, Quot.sound, sorryAx"), {}
        )
        self.assertTrue(any(v["code"] == "UNAUTHORIZED_TRANSITIVE_AXIOM" for v in violations))

    def test_missing_intermediate_is_rejected(self) -> None:
        text = self.complete_log().replace(self.block(PROBE.TARGETS[-1]), "")
        _report, violations = PROBE.make_report(text, {})
        self.assertTrue(any(v["code"] == "MISSING_TARGET_BLOCK" for v in violations))

    def test_missing_witness_projection_is_rejected(self) -> None:
        text = "".join(self.block(target) for target in PROBE.TARGETS)
        _report, violations = PROBE.make_report(text, {})
        self.assertTrue(any(v["code"] == "WITNESS_PROJECTION_MISSING" for v in violations))

    def test_incomplete_witness_projection_is_rejected(self) -> None:
        text = "".join(self.block(target) for target in PROBE.TARGETS)
        text += (
            "AUDIT_WITNESS_BEGIN|source-parameters\n"
            + "\n".join(f"{token} : MockType" for token in PROBE.REQUIRED_WITNESS_TOKENS[:-2])
            + "\nAUDIT_WITNESS_END|source-parameters\n"
        )
        _report, violations = PROBE.make_report(text, {})
        self.assertTrue(any(v["code"] == "WITNESS_PROJECTION_INCOMPLETE" for v in violations))

    def test_source_drift_is_rejected(self) -> None:
        _report, violations = PROBE.make_report(
            self.complete_log(),
            {
                "lean_subtree_matches_frozen_base": False,
                "audit_lean_tree": "audit",
                "frozen_lean_tree": "frozen",
            },
        )
        self.assertTrue(any(v["code"] == "LEAN_SUBTREE_DIFFERS_FROM_FROZEN_BASE" for v in violations))

    def test_multiline_axiom_list_parses(self) -> None:
        self.assertEqual(
            PROBE.parse_axioms("'x' depends on axioms: [propext,\n Quot.sound, Classical.choice]"),
            ["Classical.choice", "Quot.sound", "propext"],
        )

    def test_qualified_witness_names_are_required(self) -> None:
        text = "".join(self.block(target) for target in PROBE.TARGETS)
        text += (
            "AUDIT_WITNESS_BEGIN|source-parameters\n"
            "sourceQ sourcePrime selectedH selectedPair Coeff G a b\n"
            "AUDIT_WITNESS_END|source-parameters\n"
        )
        _report, violations = PROBE.make_report(text, {})
        self.assertTrue(any(v["code"] == "WITNESS_PROJECTION_INCOMPLETE" for v in violations))


if __name__ == "__main__":
    unittest.main(verbosity=2)
