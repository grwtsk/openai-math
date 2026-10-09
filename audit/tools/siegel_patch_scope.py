#!/usr/bin/env python3
"""Classify PrimeNumberTheoremAnd compatibility-patch contact with Siegel-zero source."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_changed_files(text: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    pattern = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)
    for match in pattern.finditer(text):
        records.append({"from": match.group(1), "to": match.group(2)})
    return records


def parse_file_sections(text: str) -> list[dict[str, Any]]:
    matches = list(re.finditer(r"^diff --git a/(.+?) b/(.+?)$", text, re.MULTILINE))
    sections: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.start():end]
        additions = 0
        deletions = 0
        for line in body.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                continue
            if line.startswith("+"):
                additions += 1
            elif line.startswith("-"):
                deletions += 1
        sections.append({
            "from": match.group(1),
            "to": match.group(2),
            "bytes": len(body.encode("utf-8")),
            "sha256": sha256_bytes(body.encode("utf-8")),
            "additions": additions,
            "deletions": deletions,
        })
    return sections


def classify_sections(sections: list[dict[str, Any]]) -> dict[str, Any]:
    siegel = [
        section for section in sections
        if "SiegelZero" in section["from"] or "SiegelZero" in section["to"]
    ]
    hadamard = [
        section for section in sections
        if section["from"].endswith("SiegelZeros/HadamardSupport.lean")
        or section["to"].endswith("SiegelZeros/HadamardSupport.lean")
    ]
    return {
        "siegel_zero_sections": siegel,
        "hadamard_support_sections": hadamard,
        "siegel_zero_file_count": len(siegel),
        "hadamard_support_file_count": len(hadamard),
        "hadamard_support_directly_modified": bool(hadamard),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# PNT+ patch contact with Landau–Siegel source",
        "",
        f"- Patch: `{report['patch_path']}`",
        f"- Patch bytes: **{report['patch_bytes']:,}**",
        f"- Patch SHA-256: `{report['patch_sha256']}`",
        f"- Changed files: **{report['changed_file_count']:,}**",
        f"- Siegel-zero files directly modified: **{report['classification']['siegel_zero_file_count']:,}**",
        f"- `SiegelZeros/HadamardSupport.lean` directly modified: `{report['classification']['hadamard_support_directly_modified']}`",
        "",
        "## Directly modified Siegel-zero paths",
        "",
    ]
    sections = report["classification"]["siegel_zero_sections"]
    if sections:
        for section in sections:
            lines.append(
                f"- `{section['from']}` → `{section['to']}` — "
                f"+{section['additions']}/-{section['deletions']} — `{section['sha256']}`"
            )
    else:
        lines.append("No changed-file header names a Siegel-zero path.")
    lines += [
        "",
        "## Interpretation boundary",
        "",
        "Absence of a direct patch to `HadamardSupport.lean` does not make its effective",
        "dependency closure unpatched: imported Mathlib or other PNT+ modules may still be",
        "modified. The theorem receipt must retain the complete post-patch package tree.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patch", required=True, type=Path)
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--markdown-output", required=True, type=Path)
    args = parser.parse_args()

    raw = args.patch.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        print(json.dumps({"error": f"patch is not UTF-8: {exc}"}, indent=2))
        return 1

    sections = parse_file_sections(text)
    changed = parse_changed_files(text)
    violations: list[dict[str, str]] = []
    if not sections:
        violations.append({
            "code": "PATCH_HAS_NO_DIFF_HEADERS",
            "detail": str(args.patch),
        })
    if len(sections) != len(changed):
        violations.append({
            "code": "PATCH_SECTION_COUNT_MISMATCH",
            "detail": f"sections={len(sections)} changed={len(changed)}",
        })

    report = {
        "schema_version": "SiegelPatchScope/1",
        "patch_path": str(args.patch),
        "patch_bytes": len(raw),
        "patch_sha256": sha256_bytes(raw),
        "changed_file_count": len(changed),
        "changed_files": changed,
        "file_sections": sections,
        "classification": classify_sections(sections),
        "violations": violations,
        "limits": [
            "Changed-file-path classification only.",
            "Does not compute transitive declaration dependencies or classify patch semantics.",
            "A theorem using an unmodified file can still depend on modified imported files.",
        ],
    }

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({
        "report": str(args.json_output),
        "report_sha256": sha256_bytes(args.json_output.read_bytes()),
        "changed_files": len(changed),
        "siegel_zero_files": report["classification"]["siegel_zero_file_count"],
        "hadamard_support_directly_modified": report["classification"]["hadamard_support_directly_modified"],
        "violations": len(violations),
    }, indent=2, sort_keys=True))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
