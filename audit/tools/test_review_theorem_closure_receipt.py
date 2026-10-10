#!/usr/bin/env python3
"""Hostile tests for review_theorem_closure_receipt.py."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("review_theorem_closure_receipt.py")
SPEC = importlib.util.spec_from_file_location(
    "review_theorem_closure_receipt", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
REVIEW = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = REVIEW
SPEC.loader.exec_module(REVIEW)


class AggregateInterpretationTests(unittest.TestCase):
    def test_direct_root_has_no_expected_mismatch(self) -> None:
        expectation = REVIEW.Expectation(
            key="direct",
            configured_solution_module="OAI.Direct",
            declaration_root_module="OAI.Direct",
        )
        self.assertIsNone(REVIEW.expected_legacy_mismatch(expectation))

    def test_aggregate_root_has_exact_expected_legacy_mismatch(self) -> None:
        expectation = REVIEW.Expectation(
            key="aggregate",
            configured_solution_module="OAI.Aggregate",
            declaration_root_module="OAI.Aggregate.Theorem",
        )
        self.assertEqual(
            REVIEW.expected_legacy_mismatch(expectation),
            "solution_module_mismatch: expected "
            "'OAI.Aggregate.Theorem', observed 'OAI.Aggregate'",
        )


class StatementRegionTests(unittest.TestCase):
    def test_region_hashes_are_keyed_by_exact_theorem_name(self) -> None:
        regions = [
            {
                "theorem": "OAI.A.t",
                "normalized_statement_sha256": "aaa",
            },
            {
                "theorem": "OAI.B.t",
                "normalized_statement_sha256": "bbb",
            },
        ]
        self.assertEqual(
            REVIEW.region_hashes(regions),
            {"OAI.A.t": "aaa", "OAI.B.t": "bbb"},
        )


class RouteComparisonTests(unittest.TestCase):
    def test_disjoint_local_routes_can_share_external_roots_and_aggregate(self) -> None:
        inventory = {
            "targets": {
                "landau_siegel_geometric": {
                    "modules": ["OAI.G1", "OAI.G2"],
                    "root_module": "OAI.G2",
                    "external_imports": ["Mathlib", "External.Geometry"],
                    "files": {
                        "OAI.G1": {"sha256": "g1"},
                        "OAI.G2": {"sha256": "g2"},
                    },
                    "comparator": {
                        "solution_module": "OAI.NumberTheory.SiegelZeros.Main"
                    },
                },
                "landau_siegel_analytic": {
                    "modules": ["OAI.A1", "OAI.A2"],
                    "root_module": "OAI.A2",
                    "external_imports": ["Mathlib", "External.Analytic"],
                    "files": {
                        "OAI.A1": {"sha256": "a1"},
                        "OAI.A2": {"sha256": "a2"},
                    },
                    "comparator": {
                        "solution_module": "OAI.NumberTheory.SiegelZeros.Main"
                    },
                },
            }
        }
        result = REVIEW.compare_routes(inventory)
        self.assertEqual(result["shared_local_module_count"], 0)
        self.assertEqual(result["shared_source_blob_count"], 0)
        self.assertEqual(result["shared_external_imports"], ["Mathlib"])
        self.assertTrue(result["same_configured_solution_aggregate"])
        self.assertFalse(result["geometric_imports_analytic_declaration_root"])
        self.assertFalse(result["analytic_imports_geometric_declaration_root"])
        self.assertEqual(
            result["classification"],
            "DISJOINT_LOCAL_DECLARATION_CLOSURES_WITH_SHARED_AGGREGATE_"
            "PENDING_CAUSAL_INDEPENDENCE_REVIEW",
        )

    def test_shared_blob_is_detected_even_under_distinct_module_names(self) -> None:
        inventory = {
            "targets": {
                "landau_siegel_geometric": {
                    "modules": ["OAI.G"],
                    "root_module": "OAI.G",
                    "external_imports": [],
                    "files": {"OAI.G": {"sha256": "same"}},
                    "comparator": {"solution_module": "OAI.Main"},
                },
                "landau_siegel_analytic": {
                    "modules": ["OAI.A"],
                    "root_module": "OAI.A",
                    "external_imports": [],
                    "files": {"OAI.A": {"sha256": "same"}},
                    "comparator": {"solution_module": "OAI.Main"},
                },
            }
        }
        result = REVIEW.compare_routes(inventory)
        self.assertEqual(result["shared_local_module_count"], 0)
        self.assertEqual(result["shared_source_blob_count"], 1)
        self.assertEqual(result["shared_source_blob_sha256"], ["same"])


class StablePolicyTests(unittest.TestCase):
    def test_base_revision_is_full_sha(self) -> None:
        self.assertRegex(REVIEW.BASE_REV, r"^[0-9a-f]{40}$")

    def test_expectation_keys_are_unique(self) -> None:
        keys = [item.key for item in REVIEW.EXPECTATIONS]
        self.assertEqual(len(keys), len(set(keys)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
