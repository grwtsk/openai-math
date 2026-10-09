#!/usr/bin/env python3
"""Turn marked Lean `#check` / `#print axioms` output into a receipt."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

TARGETS = (
    "OAI.riemannZeta_ne_zero_of_seven_eighths_lt_re",
    "OAI.DirichletCharacter.LFunction_ne_zero_of_seven_eighths_lt_re",
)
ALLOWED_AXIOMS = {"propext", "Quot.sound", "Classical.choice"}
BEGIN = "AUDIT_TARGET_BEGIN|"
END = "AUDIT_TARGET_END|"


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
    raw = block[start:end]
    return sorted({piece.strip().strip("'`") for piece in raw.split(",") if piece.strip()})


def type_projection(block: str) -> str:
    marker = re.search(r"depends on axioms\s*:", block, re.IGNORECASE)
    prefix = block[:marker.start()] if marker else block
    lines = [line.rstrip() for line in prefix.strip().splitlines()]
    return "\n".join(lines).strip()


def make_report(text: str, metadata: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    blocks = extract_blocks(text)
    violations: list[dict[str, str]] = []
    results: list[dict[str, Any]] = []
    if metadata.get("lean_subtree_matches_frozen_base") is False:
        violations.append({
            "code": "LEAN_SUBTREE_DIFFERS_FROM_FROZEN_BASE",
            "detail": f"audit {metadata.get('audit_lean_tree')} != frozen {metadata.get('frozen_lean_tree')}",
        })

    extra = sorted(set(blocks) - set(TARGETS))
    if extra:
        violations.append({"code": "UNEXPECTED_TARGET_BLOCK", "detail": repr(extra)})

    for target in TARGETS:
        if target not in blocks:
            violations.append({"code": "MISSING_TARGET_BLOCK", "detail": target})
            continue
        block = blocks[target]
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

    report = {
        "schema_version": "LeanAxiomProbe/1",
        "metadata": metadata,
        "target_count": len(TARGETS),
        "resolved_target_count": len(results),
        "targets": results,
        "violations": violations,
        "limits": [
            "The probe reports axioms recorded by the selected Lean environment; it is not an independent kernel.",
            "The type projection is compiler output and must be interpreted under the recorded toolchain and effective dependencies.",
            "A permitted-axiom result does not establish manuscript fidelity, originality, or mathematical peer review.",
        ],
    }
    return report, violations


def render_markdown(report: dict[str, Any]) -> str:
    meta = report["metadata"]
    lines = [
        "# Quasi-Riemann theorem axiom probe",
        "",
        f"- Frozen source revision: `{meta.get('frozen_base_revision')}`",
        f"- Frozen Lean tree: `{meta.get('frozen_lean_tree')}`",
        f"- Audit head: `{meta.get('audit_head_commit')}`",
        f"- Audit Lean tree: `{meta.get('audit_lean_tree')}`",
        f"- Lean subtree matches frozen source: `{meta.get('lean_subtree_matches_frozen_base')}`",
        f"- Lean toolchain: `{meta.get('lean_toolchain')}`",
        f"- Probe log SHA-256: `{meta.get('probe_log_sha256')}`",
        "",
        "## Targets",
        "",
    ]
    for target in report["targets"]:
        lines += [
            f"### `{target['target']}`",
            "",
            f"Permitted transitive axioms observed: `{target['axioms']}`",
            "",
            "```text",
            target["type_projection"],
            "```",
            "",
        ]
    lines += ["## Policy result", ""]
    if report["violations"]:
        for violation in report["violations"]:
            lines.append(f"- **{violation['code']}**: {violation['detail']}")
    else:
        lines.append("No axiom outside `propext`, `Quot.sound`, and `Classical.choice` was reported for the selected declarations.")
    lines += [
        "",
        "## Boundary",
        "",
        "This receipt is a primary-Lean environment observation. It does not replace Comparator's clean-room contract, an independent kernel, or statement-to-manuscript review.",
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
    parser.add_argument("--dependency-receipt-sha256")
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
        "dependency_receipt_sha256": args.dependency_receipt_sha256,
    }
    report, violations = make_report(text, metadata)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "quasi-riemann-axiom-probe.json"
    md_path = args.output_dir / "quasi-riemann-axiom-probe.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    receipt = {
        "schema_version": "LeanAxiomProbeReceipt/1",
        "json_path": str(json_path),
        "json_sha256": sha256_bytes(json_path.read_bytes()),
        "markdown_path": str(md_path),
        "markdown_sha256": sha256_bytes(md_path.read_bytes()),
        "log_path": str(args.log),
        "log_sha256": sha256_bytes(raw),
    }
    (args.output_dir / "quasi-riemann-axiom-probe-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({**receipt, "violations": len(violations)}, indent=2, sort_keys=True))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
