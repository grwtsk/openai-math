#!/usr/bin/env python3
"""Deterministic static integrity scan for the frozen OpenAI math Lean tree.

This is a lexical and repository-structure audit, not a Lean parser and not a
mathematical correctness certificate. It deliberately records its limits.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

BASE_REV = "fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb"
APPROVED_FOUNDATIONAL_AXIOMS = {"propext", "Quot.sound", "Classical.choice"}
SUPPORT_ONLY_CONFIGS = {
    "CharacterVarietiesAllSeamsSupport.json",
    "CartierChartCompactnessSupport.json",
    "SurfaceConeCandidateSupport.json",
    "TraceIdealTransportSupport.json",
    "HoneycombBridgeMassSupport.json",
}

ROOT = Path(__file__).resolve().parents[2]
LEAN_ROOT = ROOT / "lean"
REPORT_ROOT = ROOT / "audit" / "reports" / f"openai-math-{BASE_REV[:12]}"


@dataclass(frozen=True)
class Finding:
    category: str
    severity: str
    path: str
    line: int
    symbol: str
    snippet: str
    note: str = ""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_git(*args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.stdout.strip()


def strip_lean_comments_and_strings(text: str) -> str:
    """Replace comments/strings with spaces while preserving newlines.

    Handles nested /- -/ comments, -- comments, ordinary strings, and Lean raw
    strings r#"..."#. Syntax quotations remain visible because they can produce
    declarations or proof terms and are part of the metaprogramming surface.
    """

    out: list[str] = []
    i = 0
    n = len(text)
    block_depth = 0
    line_comment = False
    string = False
    raw_hashes: str | None = None

    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if line_comment:
            if c == "\n":
                line_comment = False
                out.append("\n")
            else:
                out.append(" ")
            i += 1
            continue

        if block_depth:
            if c == "/" and nxt == "-":
                block_depth += 1
                out.extend("  ")
                i += 2
            elif c == "-" and nxt == "/":
                block_depth -= 1
                out.extend("  ")
                i += 2
            else:
                out.append("\n" if c == "\n" else " ")
                i += 1
            continue

        if raw_hashes is not None:
            close = '"' + raw_hashes
            if text.startswith(close, i):
                out.extend(" " * len(close))
                i += len(close)
                raw_hashes = None
            else:
                out.append("\n" if c == "\n" else " ")
                i += 1
            continue

        if string:
            if c == "\\" and i + 1 < n:
                out.extend("  ")
                i += 2
            elif c == '"':
                string = False
                out.append(" ")
                i += 1
            else:
                out.append("\n" if c == "\n" else " ")
                i += 1
            continue

        if c == "-" and nxt == "-":
            line_comment = True
            out.extend("  ")
            i += 2
            continue
        if c == "/" and nxt == "-":
            block_depth = 1
            out.extend("  ")
            i += 2
            continue

        raw = re.match(r'r(#+)"', text[i:])
        if raw:
            token = raw.group(0)
            raw_hashes = raw.group(1)
            out.extend(" " * len(token))
            i += len(token)
            continue

        if c == '"':
            string = True
            out.append(" ")
            i += 1
            continue

        out.append(c)
        i += 1

    return "".join(out)


def line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def line_snippet(raw_lines: list[str], line: int) -> str:
    if 1 <= line <= len(raw_lines):
        return raw_lines[line - 1].strip()[:300]
    return ""


def add_regex_findings(
    findings: list[Finding],
    *,
    category: str,
    severity: str,
    path: Path,
    raw: str,
    stripped: str,
    pattern: str,
    symbol_group: int | None = None,
    flags: int = re.MULTILINE,
    note: str = "",
) -> None:
    raw_lines = raw.splitlines()
    for match in re.finditer(pattern, stripped, flags):
        line = line_for_offset(stripped, match.start())
        symbol = match.group(symbol_group) if symbol_group else match.group(0).strip()
        findings.append(
            Finding(
                category=category,
                severity=severity,
                path=str(path.relative_to(ROOT)),
                line=line,
                symbol=symbol[:200],
                snippet=line_snippet(raw_lines, line),
                note=note,
            )
        )


def scan_lean_tree() -> tuple[list[Finding], dict[str, Any], dict[str, set[str]]]:
    findings: list[Finding] = []
    counts: Counter[str] = Counter()
    imports: dict[str, set[str]] = {}
    file_hashes: dict[str, str] = {}

    lean_files = sorted(LEAN_ROOT.rglob("*.lean"))
    for path in lean_files:
        rel = str(path.relative_to(ROOT))
        raw_bytes = path.read_bytes()
        raw = raw_bytes.decode("utf-8")
        stripped = strip_lean_comments_and_strings(raw)
        file_hashes[rel] = sha256_bytes(raw_bytes)
        counts["lean_files"] += 1
        counts["lean_bytes"] += len(raw_bytes)
        if rel.startswith("lean/OAI/") or rel == "lean/OAI.lean":
            counts["oai_files"] += 1
        if rel.startswith("lean/ComparatorChallenges/"):
            counts["challenge_files"] += 1

        modules: set[str] = set()
        for m in re.finditer(r"(?m)^\s*import\s+([^\s]+)", stripped):
            modules.add(m.group(1))
        imports[rel] = modules

        if re.search(r"(?m)^\s*import\s+Mathlib\s*$", stripped):
            counts["broad_import_mathlib_files"] += 1
            findings.append(Finding(
                "broad_import_mathlib", "medium", rel,
                next(i for i, x in enumerate(stripped.splitlines(), 1) if re.match(r"^\s*import\s+Mathlib\s*$", x)),
                "Mathlib", "import Mathlib",
                "Broad umbrella import expands the elaboration and dependency surface.",
            ))

        if rel.startswith("lean/OAI/"):
            for module in sorted(modules):
                if module.startswith("ComparatorChallenges"):
                    line = next(
                        i for i, x in enumerate(stripped.splitlines(), 1)
                        if re.match(rf"^\s*import\s+{re.escape(module)}\s*$", x)
                    )
                    findings.append(Finding(
                        "challenge_imported_by_solution", "critical", rel, line,
                        module, line_snippet(raw.splitlines(), line),
                        "Solution code must not depend on a challenge declaration containing sorry.",
                    ))

        declarations = [
            ("axiom_declaration", "critical", r"(?m)^\s*(?:(?:private|protected)\s+)*axiom\s+([^\s:({]+)"),
            ("opaque_declaration", "high", r"(?m)^\s*(?:(?:private|protected|noncomputable)\s+)*opaque\s+([^\s:({]+)"),
            ("unsafe_declaration", "high", r"(?m)^\s*(?:(?:private|protected)\s+)*unsafe\s+(?:def|theorem|instance|abbrev)\s+([^\s:({]+)"),
            ("extern_declaration", "critical", r"(?m)^\s*@[\w\[\](),\s]*extern\s+([^\s:({]+)"),
        ]
        for cat, sev, pattern in declarations:
            add_regex_findings(
                findings, category=cat, severity=sev, path=path,
                raw=raw, stripped=stripped, pattern=pattern, symbol_group=1,
            )

        token_specs = [
            ("sorry_token", "critical", r"\bsorry\b"),
            ("admit_token", "critical", r"\badmit\b"),
            ("sorryAx_reference", "critical", r"\bsorryAx\b"),
            ("native_decide", "high", r"\bnative_decide\b"),
            ("exact_decide", "medium", r"\bexact_decide\b"),
            ("implemented_by", "critical", r"\bimplemented_by\b"),
            ("run_tac", "medium", r"\brun_tac\b"),
            ("lean_elab_api", "medium", r"\bLean\.Elab\b|\bLean\.Meta\b|\bLean\.Core\b"),
        ]
        for cat, sev, pattern in token_specs:
            add_regex_findings(
                findings, category=cat, severity=sev, path=path,
                raw=raw, stripped=stripped, pattern=pattern,
            )

        option_specs = [
            ("autoImplicit_true", "medium", r"(?m)^\s*set_option\s+autoImplicit\s+true\b"),
            ("maxHeartbeats", "low", r"(?m)^\s*set_option\s+maxHeartbeats\s+([^\s]+)"),
            ("maxRecDepth", "low", r"(?m)^\s*set_option\s+maxRecDepth\s+([^\s]+)"),
            ("synthInstance_maxHeartbeats", "low", r"(?m)^\s*set_option\s+synthInstance\.maxHeartbeats\s+([^\s]+)"),
            ("warningAsError_false", "medium", r"(?m)^\s*set_option\s+warningAsError\s+false\b"),
        ]
        for cat, sev, pattern in option_specs:
            add_regex_findings(
                findings, category=cat, severity=sev, path=path,
                raw=raw, stripped=stripped, pattern=pattern,
                symbol_group=1 if "([^" in pattern else None,
            )

        add_regex_findings(
            findings, category="local_instance_priority", severity="low", path=path,
            raw=raw, stripped=stripped,
            pattern=r"(?m)^\s*(?:local\s+)?instance\s*\(priority\s*:=\s*([^\)]+)\)",
            symbol_group=1,
            note="Priority-sensitive instance resolution should be captured in theorem receipts.",
        )
        add_regex_findings(
            findings, category="local_irreducible", severity="medium", path=path,
            raw=raw, stripped=stripped,
            pattern=r"(?m)^\s*attribute\s+\[local\s+irreducible\]\s+(.+)$",
            symbol_group=1,
            note="Local reducibility changes can materially affect elaboration and replay.",
        )

    by_category = Counter(f.category for f in findings)
    by_severity = Counter(f.severity for f in findings)
    summary = {
        **dict(sorted(counts.items())),
        "finding_counts_by_category": dict(sorted(by_category.items())),
        "finding_counts_by_severity": dict(sorted(by_severity.items())),
        "file_hashes": file_hashes,
    }
    return findings, summary, imports


def module_to_path(module: str) -> Path:
    return LEAN_ROOT / (module.replace(".", "/") + ".lean")


def scan_comparator_configs() -> dict[str, Any]:
    directory = LEAN_ROOT / "ComparatorChallenges"
    configs: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    theorem_owners: defaultdict[str, list[str]] = defaultdict(list)
    config_files = sorted(directory.glob("*.json"))

    for path in config_files:
        rel = str(path.relative_to(ROOT))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            problems.append({"severity": "critical", "path": rel, "kind": "invalid_json", "detail": str(exc)})
            continue

        challenge = data.get("challenge_module")
        solution = data.get("solution_module")
        theorems = data.get("theorem_names", [])
        definitions = data.get("definition_names", [])
        axioms = data.get("permitted_axioms", [])
        enable_nanoda = data.get("enable_nanoda")

        challenge_path = module_to_path(challenge) if isinstance(challenge, str) else None
        solution_path = module_to_path(solution) if isinstance(solution, str) else None
        if not challenge or not challenge_path or not challenge_path.exists():
            problems.append({"severity": "critical", "path": rel, "kind": "missing_challenge_module", "detail": challenge})
        if not solution or not solution_path or not solution_path.exists():
            problems.append({"severity": "critical", "path": rel, "kind": "missing_solution_module", "detail": solution})
        if not theorems and not definitions:
            problems.append({"severity": "high", "path": rel, "kind": "empty_comparison_target", "detail": None})
        unexpected = sorted(set(axioms) - APPROVED_FOUNDATIONAL_AXIOMS)
        if unexpected:
            problems.append({"severity": "critical", "path": rel, "kind": "unexpected_permitted_axioms", "detail": unexpected})
        for theorem in theorems:
            theorem_owners[theorem].append(path.name)

        configs.append({
            "path": rel,
            "sha256": sha256_bytes(path.read_bytes()),
            "challenge_module": challenge,
            "challenge_exists": bool(challenge_path and challenge_path.exists()),
            "solution_module": solution,
            "solution_exists": bool(solution_path and solution_path.exists()),
            "theorem_names": theorems,
            "definition_names": definitions,
            "permitted_axioms": axioms,
            "enable_nanoda": enable_nanoda,
            "scope_hint": "SUPPORTING_RESULT_ONLY" if path.name in SUPPORT_ONLY_CONFIGS else "UNREVIEWED",
        })

    duplicates = {
        theorem: sorted(owners)
        for theorem, owners in theorem_owners.items()
        if len(owners) > 1
    }
    for theorem, owners in duplicates.items():
        problems.append({"severity": "medium", "path": "lean/ComparatorChallenges", "kind": "duplicate_theorem_target", "detail": {theorem: owners}})

    return {
        "config_count": len(config_files),
        "configs": configs,
        "problems": problems,
        "duplicate_theorem_targets": duplicates,
        "nanoda_enabled_count": sum(1 for c in configs if c["enable_nanoda"] is True),
        "nanoda_disabled_count": sum(1 for c in configs if c["enable_nanoda"] is False),
        "nanoda_unspecified_count": sum(1 for c in configs if c["enable_nanoda"] is None),
    }


def parse_formalization_main_results() -> dict[str, Any]:
    path = LEAN_ROOT / "formalization.yaml"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    in_main = False
    current: dict[str, str] = {}
    results: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal current
        if current:
            results.append(current)
            current = {}

    for line in lines:
        if re.match(r"^\s*main_results:\s*$", line):
            in_main = True
            continue
        if in_main and re.match(r"^[^\s#]", line):
            flush()
            in_main = False
        if not in_main:
            continue
        m = re.match(r"^\s*-\s+comparator_config:\s*(.+?)\s*$", line)
        if m:
            flush()
            current["comparator_config"] = m.group(1).strip('"')
            continue
        for key in ("declaration", "file"):
            m = re.match(rf"^\s+{key}:\s*(.+?)\s*$", line)
            if m:
                current[key] = m.group(1).strip('"')
                break
    flush()

    problems: list[dict[str, Any]] = []
    seen_decl: defaultdict[str, list[int]] = defaultdict(list)
    for index, entry in enumerate(results):
        config = entry.get("comparator_config")
        declaration = entry.get("declaration")
        file_name = entry.get("file")
        if config and not (LEAN_ROOT / config).exists():
            problems.append({"severity": "critical", "index": index, "kind": "missing_config", "entry": entry})
        if file_name and not (LEAN_ROOT / file_name).exists():
            problems.append({"severity": "critical", "index": index, "kind": "missing_source_file", "entry": entry})
        if declaration:
            seen_decl[declaration].append(index)
        if config and Path(config).name in SUPPORT_ONLY_CONFIGS:
            problems.append({"severity": "high", "index": index, "kind": "support_only_config_listed_as_main_result", "entry": entry})
        if config and (LEAN_ROOT / config).exists() and declaration:
            try:
                cfg = json.loads((LEAN_ROOT / config).read_text(encoding="utf-8"))
                if declaration not in cfg.get("theorem_names", []) and declaration not in cfg.get("definition_names", []):
                    problems.append({"severity": "high", "index": index, "kind": "catalogue_declaration_not_in_config", "entry": entry})
            except Exception as exc:  # noqa: BLE001
                problems.append({"severity": "critical", "index": index, "kind": "catalogue_config_unreadable", "detail": str(exc), "entry": entry})

    duplicates = {k: v for k, v in seen_decl.items() if len(v) > 1}
    for declaration, indices in duplicates.items():
        problems.append({"severity": "medium", "kind": "duplicate_main_result_declaration", "detail": {declaration: indices}})

    scope_match = re.search(r"(?m)^\s*scope:\s*[\"']?([^\"'\n]+)", text)
    source_part = text.split("related_formalizations:", 1)[0]
    source_count = len(re.findall(r"(?m)^\s*-\s+title:\s*", source_part))

    return {
        "sha256": sha256_bytes(path.read_bytes()),
        "declared_scope": scope_match.group(1).strip() if scope_match else None,
        "source_count": source_count,
        "main_result_count": len(results),
        "main_results": results,
        "problems": problems,
        "duplicate_declarations": duplicates,
    }


def scan_patches() -> dict[str, Any]:
    patch_dir = LEAN_ROOT / "patches"
    records: list[dict[str, Any]] = []
    totals = Counter()
    attribution_deltas: list[dict[str, Any]] = []

    for path in sorted(patch_dir.glob("*.patch")):
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        changed_files = re.findall(r"(?m)^diff --git a/(.+?) b/(.+?)$", text)
        additions = 0
        deletions = 0
        for line in text.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                continue
            if line.startswith("+"):
                additions += 1
            elif line.startswith("-"):
                deletions += 1
            if re.search(r"(?i)copyright|authors?:|spdx|license|adapted from", line):
                attribution_deltas.append({
                    "patch": str(path.relative_to(ROOT)),
                    "line": line[:500],
                })
        record = {
            "path": str(path.relative_to(ROOT)),
            "bytes": len(raw),
            "sha256": sha256_bytes(raw),
            "changed_file_count": len(changed_files),
            "changed_files": [{"from": a, "to": b} for a, b in changed_files],
            "additions": additions,
            "deletions": deletions,
            "large_patch": len(raw) >= 1_000_000,
        }
        records.append(record)
        totals["patch_count"] += 1
        totals["patch_bytes"] += len(raw)
        totals["changed_files"] += len(changed_files)
        totals["additions"] += additions
        totals["deletions"] += deletions
        if record["large_patch"]:
            totals["large_patch_count"] += 1

    return {
        "totals": dict(totals),
        "patches": records,
        "attribution_sensitive_diff_lines": attribution_deltas,
        "readme_sha256": sha256_bytes((patch_dir / "README.md").read_bytes()) if (patch_dir / "README.md").exists() else None,
    }


def scan_dependencies() -> dict[str, Any]:
    lakefile = LEAN_ROOT / "lakefile.lean"
    manifest = LEAN_ROOT / "lake-manifest.json"
    lake_text = lakefile.read_text(encoding="utf-8")
    requirements: list[dict[str, str]] = []
    pattern = re.compile(
        r"require\s+([^\s]+)\s+from\s+git\s+\n?\s*\"([^\"]+)\"\s+@\s+\"([0-9a-f]{40})\"",
        re.MULTILINE,
    )
    for name, url, revision in pattern.findall(lake_text):
        requirements.append({"name": name, "url": url, "revision": revision})

    manifest_data: Any = None
    manifest_error: str | None = None
    try:
        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        manifest_error = str(exc)

    return {
        "lakefile_sha256": sha256_bytes(lakefile.read_bytes()),
        "manifest_sha256": sha256_bytes(manifest.read_bytes()),
        "direct_git_requirement_count": len(requirements),
        "direct_git_requirements": requirements,
        "manifest_parse_error": manifest_error,
        "manifest_package_count": len(manifest_data.get("packages", [])) if isinstance(manifest_data, dict) else None,
        "mutates_lake_packages": ".lake" in lake_text and "git apply" not in lake_text and "applyDependencyPatch" in lake_text,
        "uses_pre_resolution_patching": "preparePatchedDependencies" in lake_text,
        "uses_post_update_patching": "post_update" in lake_text,
    }


def scan_import_graph(imports: dict[str, set[str]]) -> dict[str, Any]:
    reverse: defaultdict[str, list[str]] = defaultdict(list)
    missing_local: list[dict[str, str]] = []
    challenge_importers: list[dict[str, str]] = []
    for source, modules in imports.items():
        for module in modules:
            reverse[module].append(source)
            if module.startswith("OAI") or module.startswith("ComparatorChallenges"):
                target = module_to_path(module)
                if not target.exists():
                    missing_local.append({"source": source, "module": module})
            if source.startswith("lean/OAI/") and module.startswith("ComparatorChallenges"):
                challenge_importers.append({"source": source, "module": module})

    top_imported = sorted(
        ({"module": module, "importer_count": len(files)} for module, files in reverse.items()),
        key=lambda x: (-x["importer_count"], x["module"]),
    )[:100]
    return {
        "missing_local_module_imports": missing_local,
        "solution_to_challenge_imports": challenge_importers,
        "top_imported_modules": top_imported,
    }


def render_markdown(report: dict[str, Any]) -> str:
    s = report["lean_scan"]
    c = report["comparator"]
    f = report["formalization_catalogue"]
    p = report["patches"]
    d = report["dependencies"]
    lines = [
        "# OpenAI math integrity and rigor scan",
        "",
        f"Frozen upstream base: `{BASE_REV}`",
        f"Audit head: `{report['audit_identity']['head_commit']}`",
        f"Generated tree state: `{report['audit_identity']['head_tree']}`",
        "",
        "> This is a deterministic static audit. It is not a Lean parser, kernel replay,",
        "> statement-fidelity review, or mathematical correctness certificate.",
        "",
        "## Executive counts",
        "",
        f"- Lean files: **{s.get('lean_files', 0):,}**",
        f"- OAI files: **{s.get('oai_files', 0):,}**",
        f"- Comparator challenge files: **{s.get('challenge_files', 0):,}**",
        f"- Exact `import Mathlib` files: **{s.get('broad_import_mathlib_files', 0):,}**",
        f"- Comparator configurations: **{c['config_count']:,}**",
        f"- Formalization catalogue main-result rows: **{f['main_result_count']:,}**",
        f"- Dependency patches: **{p['totals'].get('patch_count', 0):,}**",
        f"- Dependency patch bytes: **{p['totals'].get('patch_bytes', 0):,}**",
        f"- Files modified by patches: **{p['totals'].get('changed_files', 0):,}**",
        f"- Direct pinned Git requirements parsed: **{d['direct_git_requirement_count']:,}**",
        "",
        "## Lean trust-surface findings",
        "",
        "| Category | Count |",
        "|---|---:|",
    ]
    for key, value in sorted(s["finding_counts_by_category"].items()):
        lines.append(f"| `{key}` | {value:,} |")

    lines += [
        "",
        "## Comparator cross-check",
        "",
        f"- Problems: **{len(c['problems']):,}**",
        f"- Independent-kernel flag enabled: **{c['nanoda_enabled_count']:,}**",
        f"- Independent-kernel flag disabled: **{c['nanoda_disabled_count']:,}**",
        f"- Independent-kernel flag unspecified: **{c['nanoda_unspecified_count']:,}**",
        "",
        "## Formalization catalogue cross-check",
        "",
        f"- Declared global scope: `{f['declared_scope']}`",
        f"- Source records: **{f['source_count']:,}**",
        f"- Problems: **{len(f['problems']):,}**",
        "",
        "## Patched dependency surface",
        "",
        f"- Large patches (>= 1 MB): **{p['totals'].get('large_patch_count', 0):,}**",
        f"- Added lines: **{p['totals'].get('additions', 0):,}**",
        f"- Deleted lines: **{p['totals'].get('deletions', 0):,}**",
        "",
        "The effective dependency source is the pinned commit plus the ordered patch",
        "set and resulting tree. A manifest commit alone does not identify these bytes.",
        "",
        "## Highest-severity exact findings",
        "",
    ]
    severe = [x for x in report["findings"] if x["severity"] in {"critical", "high"}]
    if not severe:
        lines.append("No critical or high lexical findings were produced by this scanner.")
    else:
        for item in severe[:250]:
            lines.append(
                f"- **{item['severity'].upper()}** `{item['category']}` — "
                f"`{item['path']}:{item['line']}` — `{item['symbol']}`"
            )
    if len(severe) > 250:
        lines.append(f"- … {len(severe) - 250:,} additional entries are retained in JSON.")

    lines += [
        "",
        "## Scanner limits",
        "",
        "- The Lean lexer is conservative and not an elaborator.",
        "- Syntax quotations and generated terms require separate metaprogramming review.",
        "- A zero lexical result does not replace `#print axioms` or kernel replay.",
        "- A compiled theorem can still formalize a weakened, vacuous, or mismatched claim.",
        "- This report does not establish originality, priority, authorship, or causal independence.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    os.chdir(ROOT)
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)

    head = run_git("rev-parse", "HEAD")
    head_tree = run_git("rev-parse", "HEAD^{tree}")
    base_tree = run_git("rev-parse", f"{BASE_REV}^{{tree}}")
    subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", BASE_REV, head], check=True)

    findings, lean_summary, imports = scan_lean_tree()
    comparator = scan_comparator_configs()
    formalization = parse_formalization_main_results()
    patches = scan_patches()
    dependencies = scan_dependencies()
    import_graph = scan_import_graph(imports)

    report = {
        "schema_version": "OpenAIMathIntegrityScan/1",
        "audit_identity": {
            "base_revision": BASE_REV,
            "base_tree": base_tree,
            "head_commit": head,
            "head_tree": head_tree,
            "scanner_path": str(Path(__file__).relative_to(ROOT)),
            "scanner_sha256": sha256_bytes(Path(__file__).read_bytes()),
        },
        "lean_scan": lean_summary,
        "findings": [asdict(x) for x in sorted(findings, key=lambda z: (z.severity, z.category, z.path, z.line, z.symbol))],
        "comparator": comparator,
        "formalization_catalogue": formalization,
        "patches": patches,
        "dependencies": dependencies,
        "import_graph": import_graph,
        "limits": [
            "Static lexical and repository-structure scan only.",
            "Does not elaborate Lean, compare theorem semantics, or replay Comparator.",
            "Does not establish mathematical correctness, originality, priority, or authorship.",
        ],
    }

    json_path = REPORT_ROOT / "integrity-scan.json"
    md_path = REPORT_ROOT / "integrity-scan.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")

    receipt = {
        "report_json": str(json_path.relative_to(ROOT)),
        "report_json_sha256": sha256_bytes(json_path.read_bytes()),
        "report_markdown": str(md_path.relative_to(ROOT)),
        "report_markdown_sha256": sha256_bytes(md_path.read_bytes()),
    }
    (REPORT_ROOT / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(json.dumps({
        "lean_files": lean_summary.get("lean_files"),
        "oai_files": lean_summary.get("oai_files"),
        "findings": len(findings),
        "comparator_configs": comparator["config_count"],
        "comparator_problems": len(comparator["problems"]),
        "catalogue_problems": len(formalization["problems"]),
        "patches": patches["totals"].get("patch_count", 0),
        **receipt,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
