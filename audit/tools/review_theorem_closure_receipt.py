#!/usr/bin/env python3
"""Validate and interpret the bounded theorem-closure inventory.

The first-pass scanner intentionally starts from the declaration-bearing
modules. Comparator may name a larger aggregate solution module. This review
binds those two layers, verifies exact challenge/solution statement-region
hashes, and measures both local and external overlap between the two
Landau–Siegel routes.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BASE_REV = "fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb"

ROOT = Path(__file__).resolve().parents[2]
RESULT_ROOT = ROOT / "audit" / "results" / "theorem-closure"
INVENTORY_PATH = RESULT_ROOT / "theorem-closure-receipt.json"
BASE_SCANNER_PATH = Path(__file__).with_name("theorem_closure_scan.py")


@dataclass(frozen=True)
class Expectation:
    key: str
    configured_solution_module: str
    declaration_root_module: str


EXPECTATIONS: tuple[Expectation, ...] = (
    Expectation(
        key="quasi_riemann_zeta",
        configured_solution_module="OAI.NumberTheory.DirichletL.Nonvanishing",
        declaration_root_module="OAI.NumberTheory.DirichletL.Nonvanishing",
    ),
    Expectation(
        key="landau_siegel_geometric",
        configured_solution_module="OAI.NumberTheory.SiegelZeros.Main",
        declaration_root_module="OAI.NumberTheory.SiegelZeros.Conclusions.Theorem",
    ),
    Expectation(
        key="landau_siegel_analytic",
        configured_solution_module="OAI.NumberTheory.SiegelZeros.Main",
        declaration_root_module=(
            "OAI.NumberTheory.SiegelZeros.Characters."
            "DirichletRealZeroBoundProof"
        ),
    ),
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_base_scanner():
    spec = importlib.util.spec_from_file_location(
        "theorem_closure_scan_for_review", BASE_SCANNER_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load base theorem closure scanner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def expected_legacy_mismatch(expectation: Expectation) -> str | None:
    if expectation.configured_solution_module == expectation.declaration_root_module:
        return None
    return (
        "solution_module_mismatch: expected "
        f"{expectation.declaration_root_module!r}, observed "
        f"{expectation.configured_solution_module!r}"
    )


def region_hashes(regions: list[dict[str, Any]]) -> dict[str, str]:
    return {
        region["theorem"]: region["normalized_statement_sha256"]
        for region in regions
    }


def validate_target(
    inventory: dict[str, Any],
    expectation: Expectation,
    base_scanner,
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    targets = inventory.get("targets", {})
    target = targets.get(expectation.key)
    if not isinstance(target, dict):
        return {}, [f"missing target inventory: {expectation.key}"]

    observed_root = target.get("root_module")
    if observed_root != expectation.declaration_root_module:
        errors.append(
            f"{expectation.key}: declaration root mismatch: {observed_root!r}"
        )

    comparator = target.get("comparator", {})
    observed_solution = comparator.get("solution_module")
    if observed_solution != expectation.configured_solution_module:
        errors.append(
            f"{expectation.key}: configured solution mismatch: "
            f"{observed_solution!r}"
        )

    closure = base_scanner.collect_closure(expectation.configured_solution_module)
    configured_modules = set(closure["modules"])
    if closure["missing_internal_imports"]:
        errors.append(
            f"{expectation.key}: configured solution closure has unresolved "
            f"internal imports: {closure['missing_internal_imports']}"
        )
    relation = (
        "CONFIGURED_SOLUTION_ROOT"
        if expectation.configured_solution_module
        == expectation.declaration_root_module
        else "TRANSITIVE_DECLARATION_ROOT"
    )
    declaration_reachable = expectation.declaration_root_module in configured_modules
    if not declaration_reachable:
        errors.append(
            f"{expectation.key}: declaration root is not reachable from "
            "the configured solution module"
        )

    legacy_problems = list(comparator.get("problems", []))
    allowed = expected_legacy_mismatch(expectation)
    unexpected_problems = [
        problem for problem in legacy_problems if problem != allowed
    ]
    if unexpected_problems:
        errors.extend(
            f"{expectation.key}: unexpected comparator inventory problem: {problem}"
            for problem in unexpected_problems
        )

    solution_hashes = region_hashes(target.get("target_regions", []))
    challenge_hashes = region_hashes(
        target.get("challenge", {}).get("target_regions", [])
    )
    statement_matches: dict[str, bool] = {}
    for theorem in target.get("theorem_names", []):
        match = (
            theorem in solution_hashes
            and theorem in challenge_hashes
            and solution_hashes[theorem] == challenge_hashes[theorem]
        )
        statement_matches[theorem] = match
        if not match:
            errors.append(
                f"{expectation.key}: challenge/solution statement hash "
                f"mismatch for {theorem}"
            )

    critical_count = target.get("critical_policy_violation_count")
    if critical_count != 0:
        errors.append(
            f"{expectation.key}: critical policy count is {critical_count!r}"
        )

    return {
        "key": expectation.key,
        "configured_solution_module": expectation.configured_solution_module,
        "declaration_root_module": expectation.declaration_root_module,
        "declaration_root_relation": relation,
        "declaration_root_reachable": declaration_reachable,
        "configured_solution_closure_module_count": len(configured_modules),
        "configured_solution_missing_internal_imports": closure[
            "missing_internal_imports"
        ],
        "legacy_inventory_problems": legacy_problems,
        "legacy_expected_aggregate_mismatch": allowed,
        "unexpected_inventory_problems": unexpected_problems,
        "challenge_solution_statement_hash_matches": statement_matches,
        "critical_policy_violation_count": critical_count,
        "configured_enable_nanoda": comparator.get("enable_nanoda"),
        "configured_permitted_axioms": comparator.get("permitted_axioms", []),
    }, errors


def compare_routes(inventory: dict[str, Any]) -> dict[str, Any]:
    targets = inventory["targets"]
    geometric = targets["landau_siegel_geometric"]
    analytic = targets["landau_siegel_analytic"]

    g_modules = set(geometric["modules"])
    a_modules = set(analytic["modules"])
    g_external = set(geometric["external_imports"])
    a_external = set(analytic["external_imports"])
    g_blobs = {info["sha256"] for info in geometric.get("files", {}).values()}
    a_blobs = {info["sha256"] for info in analytic.get("files", {}).values()}

    local_shared = g_modules & a_modules
    external_shared = g_external & a_external
    blob_shared = g_blobs & a_blobs

    return {
        "geometric_local_module_count": len(g_modules),
        "analytic_local_module_count": len(a_modules),
        "shared_local_module_count": len(local_shared),
        "shared_local_modules": sorted(local_shared),
        "geometric_external_import_count": len(g_external),
        "analytic_external_import_count": len(a_external),
        "shared_external_import_count": len(external_shared),
        "shared_external_imports": sorted(external_shared),
        "shared_source_blob_count": len(blob_shared),
        "shared_source_blob_sha256": sorted(blob_shared),
        "same_configured_solution_aggregate": (
            geometric["comparator"]["solution_module"]
            == analytic["comparator"]["solution_module"]
        ),
        "configured_solution_aggregate": geometric["comparator"][
            "solution_module"
        ],
        "geometric_imports_analytic_declaration_root": (
            analytic["root_module"] in g_modules
        ),
        "analytic_imports_geometric_declaration_root": (
            geometric["root_module"] in a_modules
        ),
        "classification": (
            "DISJOINT_LOCAL_DECLARATION_CLOSURES_WITH_SHARED_AGGREGATE_"
            "PENDING_CAUSAL_INDEPENDENCE_REVIEW"
        ),
        "interpretation": (
            "The selected local source closures share no tracked module or "
            "source blob, but both are exported through one Comparator "
            "solution aggregate and both depend on external libraries. "
            "This supports formal route separation; it does not establish "
            "causal, conceptual, or mathematical independence."
        ),
    }


def render_markdown(review: dict[str, Any]) -> str:
    lines = [
        "# Theorem-closure interpretation review",
        "",
        f"- Frozen upstream base: `{review['identity']['base_revision']}`",
        f"- Inventory SHA-256: `{review['identity']['inventory_sha256']}`",
        f"- Base scanner SHA-256: `{review['identity']['base_scanner_sha256']}`",
        f"- Review scanner SHA-256: `{review['identity']['review_scanner_sha256']}`",
        "",
        "## Statement and Comparator binding",
        "",
    ]

    for key, target in review["targets"].items():
        lines.extend(
            [
                f"### `{key}`",
                "",
                f"- Configured solution module: `{target['configured_solution_module']}`",
                f"- Declaration root: `{target['declaration_root_module']}`",
                f"- Relation: `{target['declaration_root_relation']}`",
                f"- Reachable from configured solution: "
                f"**{target['declaration_root_reachable']}**",
                f"- Critical static policy findings: "
                f"**{target['critical_policy_violation_count']}**",
                f"- Independent-kernel flag: "
                f"`{target['configured_enable_nanoda']}`",
            ]
        )
        for theorem, matches in target[
            "challenge_solution_statement_hash_matches"
        ].items():
            lines.append(
                f"- Exact normalized challenge/solution statement hash for "
                f"`{theorem}`: **{matches}**"
            )
        if target["unexpected_inventory_problems"]:
            for problem in target["unexpected_inventory_problems"]:
                lines.append(f"- Unexpected inventory problem: `{problem}`")
        elif target["legacy_expected_aggregate_mismatch"]:
            lines.append(
                "- The first-pass `solution_module_mismatch` is reclassified "
                "as an expected declaration root beneath the configured "
                "aggregate, not as a Comparator defect."
            )
        lines.append("")

    route = review["route_comparison"]
    lines.extend(
        [
            "## Landau–Siegel route relation",
            "",
            f"- Geometric local modules: **{route['geometric_local_module_count']}**",
            f"- Analytic local modules: **{route['analytic_local_module_count']}**",
            f"- Shared local modules: **{route['shared_local_module_count']}**",
            f"- Shared source blobs: **{route['shared_source_blob_count']}**",
            f"- Shared external import roots: "
            f"**{route['shared_external_import_count']}**",
            (
                "- Shared external imports: "
                + (
                    ", ".join(
                        f"`{item}`" for item in route["shared_external_imports"]
                    )
                    if route["shared_external_imports"]
                    else "none"
                )
            ),
            f"- Shared configured solution aggregate: "
            f"**{route['same_configured_solution_aggregate']}** — "
            f"`{route['configured_solution_aggregate']}`",
            f"- Classification: `{route['classification']}`",
            "",
            route["interpretation"],
            "",
            "## Boundary",
            "",
            "Exact source-region hash equality proves textual statement "
            "identity after whitespace normalization. It does not replace "
            "Lean elaboration, definitional-dependency comparison, "
            "Comparator replay, `#print axioms`, independent-kernel replay, "
            "or mathematical review.",
            "",
        ]
    )

    if review["validation_errors"]:
        lines.extend(
            ["## Validation errors", ""]
            + [f"- {error}" for error in review["validation_errors"]]
            + [""]
        )
    else:
        lines.extend(["## Validation", "", "- All interpretation checks passed.", ""])

    return "\n".join(lines)


def main() -> int:
    os.chdir(ROOT)
    if not INVENTORY_PATH.exists():
        print(f"missing inventory: {INVENTORY_PATH}", file=sys.stderr)
        return 2

    inventory_bytes = INVENTORY_PATH.read_bytes()
    inventory = json.loads(inventory_bytes.decode("utf-8"))
    base_scanner = load_base_scanner()

    errors: list[str] = []
    target_reviews: dict[str, Any] = {}
    for expectation in EXPECTATIONS:
        target_review, target_errors = validate_target(
            inventory, expectation, base_scanner
        )
        target_reviews[expectation.key] = target_review
        errors.extend(target_errors)

    if inventory.get("audit_identity", {}).get("base_revision") != BASE_REV:
        errors.append("inventory base revision mismatch")

    review = {
        "schema_version": "TheoremClosureInterpretation/2",
        "identity": {
            "base_revision": BASE_REV,
            "inventory_path": str(INVENTORY_PATH.relative_to(ROOT)),
            "inventory_sha256": sha256_bytes(inventory_bytes),
            "base_scanner_path": str(BASE_SCANNER_PATH.relative_to(ROOT)),
            "base_scanner_sha256": sha256_bytes(BASE_SCANNER_PATH.read_bytes()),
            "review_scanner_path": str(Path(__file__).relative_to(ROOT)),
            "review_scanner_sha256": sha256_bytes(Path(__file__).read_bytes()),
        },
        "targets": target_reviews,
        "route_comparison": compare_routes(inventory),
        "validation_errors": errors,
        "limits": [
            "Interprets a static source inventory only.",
            "Does not elaborate Lean, replay Comparator, or prove route independence.",
        ],
    }

    json_path = RESULT_ROOT / "theorem-closure-interpretation-v2.json"
    markdown_path = RESULT_ROOT / "theorem-closure-interpretation-v2.md"
    json_path.write_text(
        json.dumps(review, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(review), encoding="utf-8")

    receipt = {
        "schema_version": "TheoremClosureInterpretationArtifact/2",
        "review_json": str(json_path.relative_to(ROOT)),
        "review_json_sha256": sha256_bytes(json_path.read_bytes()),
        "review_markdown": str(markdown_path.relative_to(ROOT)),
        "review_markdown_sha256": sha256_bytes(markdown_path.read_bytes()),
        "validation_error_count": len(errors),
    }
    receipt_path = RESULT_ROOT / "interpretation-receipt-v2.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "validation_error_count": len(errors),
                "route_comparison": {
                    "shared_local_modules": review["route_comparison"][
                        "shared_local_module_count"
                    ],
                    "shared_external_imports": review["route_comparison"][
                        "shared_external_imports"
                    ],
                    "shared_source_blobs": review["route_comparison"][
                        "shared_source_blob_count"
                    ],
                },
                **receipt,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
