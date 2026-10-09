#!/usr/bin/env python3
"""Create a theorem-level receipt for the prescribed Kaplansky witness chain."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

TARGETS = (
    "OAI.KaplanskyCounterexample.main_theorem",
    "OAI.KaplanskyCounterexample.Prescription.Output.prescribed_main",
    "OAI.KaplanskyCounterexample.Prescription.Output.prescribed_products",
    "OAI.KaplanskyCounterexample.Prescription.finite_search_terminates",
    "OAI.mersenne_21701_prime",
    "OAI.KaplanskyCounterexample.Prescription.Output.X_global",
    "OAI.KaplanskyCounterexample.Prescription.Output.X_local",
    "OAI.KaplanskyCounterexample.Prescription.Output.forms_distinct",
)
ALLOWED_AXIOMS = {"propext", "Quot.sound", "Classical.choice"}
BEGIN = "AUDIT_TARGET_BEGIN|"
END = "AUDIT_TARGET_END|"
WITNESS_BEGIN = "AUDIT_WITNESS_BEGIN|source-parameters"
WITNESS_END = "AUDIT_WITNESS_END|source-parameters"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract_blocks(text: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    position = 0
    while True:
        start = text.find(BEGIN, position)
        if start < 0:
            break
        name_start = start + len(BEGIN)
        name_end = text.find("\n", name_start)
        if name_end < 0:
            raise ValueError("unterminated begin marker")
        target = text[name_start:name_end].strip()
        end_marker = END + target
        end = text.find(end_marker, name_end)
        if end < 0:
            raise ValueError(f"missing end marker for {target}")
        if target in blocks:
            raise ValueError(f"duplicate block for {target}")
        blocks[target] = text[name_end + 1:end]
        position = end + len(end_marker)
    return blocks


def extract_witness_projection(text: str) -> str:
    start = text.find(WITNESS_BEGIN)
    if start < 0:
        raise ValueError("missing witness begin marker")
    start = text.find("\n", start)
    if start < 0:
        raise ValueError("unterminated witness begin marker")
    end = text.find(WITNESS_END, start + 1)
    if end < 0:
        raise ValueError("missing witness end marker")
    return text[start + 1:end].strip()


def parse_axioms(block: str) -> list[str]:
    if re.search(r"does not depend on (?:any )?axioms", block, re.IGNORECASE):
        return []
    marker = re.search(r"depends on axioms\s*:\s*\[", block, re.IGNORECASE)
    if not marker:
        raise ValueError("no `#print axioms` result found")
    start = marker.end()
    end = block.find("]", start)
    if end < 0:
        raise ValueError("unterminated axiom list")
    return sorted({piece.strip().strip("'`") for piece in block[start:end].split(",") if piece.strip()})


def type_projection(block: str) -> str:
    marker = re.search(r"depends on axioms\s*:", block, re.IGNORECASE)
    prefix = block[:marker.start()] if marker else block
    return "\n".join(line.rstrip() for line in prefix.strip().splitlines()).strip()


def make_report(text: str, metadata: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    violations: list[dict[str, str]] = []
    try:
        blocks = extract_blocks(text)
    except ValueError as exc:
        blocks = {}
        violations.append({"code": "TARGET_MARKERS_UNPARSEABLE", "detail": str(exc)})

    try:
        witness_projection = extract_witness_projection(text)
    except ValueError as exc:
        witness_projection = ""
        violations.append({"code": "WITNESS_PROJECTION_MISSING", "detail": str(exc)})

    if metadata.get("lean_subtree_matches_frozen_base") is False:
        violations.append({
            "code": "LEAN_SUBTREE_DIFFERS_FROM_FROZEN_BASE",
            "detail": f"audit {metadata.get('audit_lean_tree')} != frozen {metadata.get('frozen_lean_tree')}",
        })

    unexpected = sorted(set(blocks) - set(TARGETS))
    if unexpected:
        violations.append({"code": "UNEXPECTED_TARGET_BLOCK", "detail": repr(unexpected)})

    results: list[dict[str, Any]] = []
    for target in TARGETS:
        block = blocks.get(target)
        if block is None:
            violations.append({"code": "MISSING_TARGET_BLOCK", "detail": target})
            continue
        try:
            axioms = parse_axioms(block)
        except ValueError as exc:
            violations.append({"code": "AXIOM_OUTPUT_UNPARSEABLE", "detail": f"{target}: {exc}"})
            continue
        unauthorized = sorted(set(axioms) - ALLOWED_AXIOMS)
        if unauthorized:
            violations.append({
                "code": "UNAUTHORIZED_TRANSITIVE_AXIOM",
                "detail": f"{target}: {unauthorized!r}",
            })
        results.append({
            "target": target,
            "axioms": axioms,
            "permitted_axioms": sorted(ALLOWED_AXIOMS),
            "unauthorized_axioms": unauthorized,
            "type_projection": type_projection(block),
            "raw_block_sha256": sha256_bytes(block.encode("utf-8")),
        })

    if witness_projection:
        required_tokens = (
            "sourceQ", "sourcePrime", "selectedH", "selectedPair", "Coeff", "G", " a", " b",
        )
        missing = [token for token in required_tokens if token not in witness_projection]
        if missing:
            violations.append({
                "code": "WITNESS_PROJECTION_INCOMPLETE",
                "detail": repr(missing),
            })

    report = {
        "schema_version": "KaplanskyWitnessProbe/1",
        "metadata": metadata,
        "target_count": len(TARGETS),
        "resolved_target_count": len(results),
        "targets": results,
        "witness_projection": witness_projection,
        "witness_projection_sha256": sha256_bytes(witness_projection.encode("utf-8")),
        "violations": violations,
        "limits": [
            "The probe observes the primary Lean environment and is not an independent kernel.",
            "Printing witness types does not reduce the noncomputable least-search objects to a serialized finite table.",
            "A permitted-axiom result does not establish manuscript fidelity, originality, or independent mathematical review.",
            "The finite incidence, prime, matrix, and group-algebra certificates require separate semantic and resource review.",
        ],
    }
    return report, violations


def render_markdown(report: dict[str, Any]) -> str:
    meta = report["metadata"]
    lines = [
        "# Kaplansky prescribed-witness axiom probe",
        "",
        f"- Frozen source revision: `{meta.get('frozen_base_revision')}`",
        f"- Frozen Lean tree: `{meta.get('frozen_lean_tree')}`",
        f"- Audit head: `{meta.get('audit_head_commit')}`",
        f"- Audit Lean tree: `{meta.get('audit_lean_tree')}`",
        f"- Lean subtree matches frozen source: `{meta.get('lean_subtree_matches_frozen_base')}`",
        f"- Lean toolchain: `{meta.get('lean_toolchain')}`",
        f"- Probe log SHA-256: `{meta.get('probe_log_sha256')}`",
        "",
        "## Theorem and certificate targets",
        "",
    ]
    for target in report["targets"]:
        lines += [
            f"### `{target['target']}`",
            "",
            f"Observed transitive axioms: `{target['axioms']}`",
            "",
            "```text",
            target["type_projection"],
            "```",
            "",
        ]
    lines += [
        "## Named witness projection",
        "",
        "```text",
        report["witness_projection"],
        "```",
        "",
        "## Policy result",
        "",
    ]
    if report["violations"]:
        for violation in report["violations"]:
            lines.append(f"- **{violation['code']}**: {violation['detail']}")
    else:
        lines.append("No axiom outside `propext`, `Quot.sound`, and `Classical.choice` was reported for the selected chain.")
    lines += [
        "",
        "## Boundary",
        "",
        "This receipt binds named definitions and primary-kernel axiom output. It does not yet serialize the least successful incidence pair, independently recompute the Lucas–Lehmer certificate, or satisfy Comparator's clean-room contract.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--frozen-base-revision", required=True)
    parser.add_argument("--frozen-base-tree", required=True)
    parser.add_argument("--frozen-lean-tree", required=True)
    parser.add_argument("--audit-head-commit", required=True)
    parser.add_argument("--audit-head-tree", required=True)
    parser.add_argument("--audit-lean-tree", required=True)
    parser.add_argument("--lean-toolchain", required=True)
    args = parser.parse_args()

    raw = args.log.read_bytes()
    text = raw.decode("utf-8", "strict")
    metadata = {
        "frozen_base_revision": args.frozen_base_revision,
        "frozen_base_tree": args.frozen_base_tree,
        "frozen_lean_tree": args.frozen_lean_tree,
        "audit_head_commit": args.audit_head_commit,
        "audit_head_tree": args.audit_head_tree,
        "audit_lean_tree": args.audit_lean_tree,
        "lean_subtree_matches_frozen_base": args.audit_lean_tree == args.frozen_lean_tree,
        "lean_toolchain": args.lean_toolchain,
        "probe_log": str(args.log),
        "probe_log_sha256": sha256_bytes(raw),
    }
    report, violations = make_report(text, metadata)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "kaplansky-witness-probe.json"
    md_path = args.output_dir / "kaplansky-witness-probe.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    receipt = {
        "schema_version": "KaplanskyWitnessProbeReceipt/1",
        "json_path": str(json_path),
        "json_sha256": sha256_bytes(json_path.read_bytes()),
        "markdown_path": str(md_path),
        "markdown_sha256": sha256_bytes(md_path.read_bytes()),
        "log_path": str(args.log),
        "log_sha256": sha256_bytes(raw),
    }
    (args.output_dir / "kaplansky-witness-probe-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({**receipt, "violations": len(violations)}, indent=2, sort_keys=True))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
