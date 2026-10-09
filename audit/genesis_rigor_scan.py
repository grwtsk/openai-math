#!/usr/bin/env python3
"""Deterministic static trust-surface scan for the OpenAI math fork.

This scanner is intentionally conservative. It records exact source observations,
review signals, and policy violations without treating ordinary Lean constructs as
proof defects. It uses only Python's standard library and the checked-out Git tree.
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
LEAN_ROOT = ROOT / "lean"
OUT = ROOT / "audit" / "results"
OUT.mkdir(parents=True, exist_ok=True)


def run(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def tracked_files() -> list[Path]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [ROOT / p.decode("utf-8") for p in raw.split(b"\0") if p]


def git_modes() -> dict[str, str]:
    raw = run("git", "ls-files", "-s")
    modes: dict[str, str] = {}
    for line in raw.splitlines():
        match = re.match(r"^(\d+)\s+[0-9a-f]+\s+\d+\t(.+)$", line)
        if match:
            modes[match.group(2)] = match.group(1)
    return modes


def strip_lean_comments_and_strings(text: str) -> str:
    """Replace comments and string contents with spaces while preserving newlines.

    Lean block comments nest. This is a lexical approximation, not a parser, but it
    sharply separates actual tokens from documentation and English substrings.
    """
    out = list(text)
    i = 0
    block_depth = 0
    in_string = False
    in_char = False
    escaped = False
    while i < len(text):
        if block_depth:
            if text.startswith("/-", i):
                out[i] = out[i + 1] = " "
                block_depth += 1
                i += 2
                continue
            if text.startswith("-/", i):
                out[i] = out[i + 1] = " "
                block_depth -= 1
                i += 2
                continue
            if text[i] != "\n":
                out[i] = " "
            i += 1
            continue
        if in_string:
            if text[i] != "\n":
                out[i] = " "
            if escaped:
                escaped = False
            elif text[i] == "\\":
                escaped = True
            elif text[i] == '"':
                in_string = False
            i += 1
            continue
        if in_char:
            if text[i] != "\n":
                out[i] = " "
            if escaped:
                escaped = False
            elif text[i] == "\\":
                escaped = True
            elif text[i] == "'":
                in_char = False
            i += 1
            continue
        if text.startswith("--", i):
            while i < len(text) and text[i] != "\n":
                out[i] = " "
                i += 1
            continue
        if text.startswith("/-", i):
            out[i] = out[i + 1] = " "
            block_depth = 1
            i += 2
            continue
        if text[i] == '"':
            out[i] = " "
            in_string = True
            i += 1
            continue
        # Lean character literals are uncommon in source scans; this heuristic
        # avoids erasing identifier apostrophes by requiring a closing quote nearby.
        if text[i] == "'" and i + 2 < len(text) and "'" in text[i + 1 : i + 6]:
            out[i] = " "
            in_char = True
            i += 1
            continue
        i += 1
    return "".join(out)


@dataclass(frozen=True)
class Finding:
    token: str
    path: str
    line: int
    path_class: str
    snippet: str


def path_class(rel: str) -> str:
    if rel.startswith("lean/ComparatorChallenges/"):
        return "challenge"
    if rel == "lean/OAI.lean" or rel.startswith("lean/OAI/"):
        return "solution"
    if rel.startswith("lean/patches/"):
        return "patch"
    if rel.startswith("lean/docs/"):
        return "scope_doc"
    return "other"


TOKEN_PATTERNS: dict[str, re.Pattern[str]] = {
    "sorry": re.compile(r"\bsorry\b"),
    "admit": re.compile(r"\badmit\b"),
    "axiom_decl": re.compile(r"(?m)^\s*axiom\s+"),
    "opaque_decl": re.compile(r"(?m)^\s*opaque\s+"),
    "unsafe_decl": re.compile(r"(?m)^\s*unsafe\s+(?:def|theorem|opaque|instance)\s+"),
    "extern_decl": re.compile(r"(?m)^\s*@[\[]?extern\b|(?m)^\s*extern\s+"),
    "implemented_by": re.compile(r"\bimplemented_by\b"),
    "native_decide": re.compile(r"\bnative_decide\b"),
    "exact_decide_tactic": re.compile(r"\bby\s+exact_decide\b"),
    "run_tac": re.compile(r"\brun_tac\b"),
    "classical_choose": re.compile(r"\bClassical\.choose\b"),
    "exists_choose": re.compile(r"\bExists\.choose\b"),
    "false_elim": re.compile(r"\bFalse\.elim\b"),
    "subsingleton_elim": re.compile(r"\bSubsingleton\.elim\b"),
    "local_instance": re.compile(r"(?m)^\s*local\s+instance\b"),
    "local_instance_attribute": re.compile(r"attribute\s*\[\s*local\s+instance\s*\]"),
    "noncomputable": re.compile(r"(?m)^\s*noncomputable\s+(?:section|def|instance)\b"),
    "autoimplicit_true": re.compile(r"set_option\s+autoImplicit\s+true\b"),
    "resource_option": re.compile(r"set_option\s+(?:maxRecDepth|maxHeartbeats|synthInstance\.maxHeartbeats)\b"),
    "broad_mathlib_import": re.compile(r"(?m)^\s*import\s+Mathlib\s*$"),
}


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def source_findings(lean_files: list[Path]) -> tuple[list[Finding], dict[str, str]]:
    findings: list[Finding] = []
    stripped_by_rel: dict[str, str] = {}
    for path in lean_files:
        rel = path.relative_to(ROOT).as_posix()
        original = path.read_text(encoding="utf-8")
        stripped = strip_lean_comments_and_strings(original)
        stripped_by_rel[rel] = stripped
        original_lines = original.splitlines()
        for token, pattern in TOKEN_PATTERNS.items():
            for match in pattern.finditer(stripped):
                line = line_of(stripped, match.start())
                snippet = original_lines[line - 1].strip() if line <= len(original_lines) else ""
                findings.append(Finding(token, rel, line, path_class(rel), snippet[:300]))
    findings.sort(key=lambda x: (x.path, x.line, x.token))
    return findings, stripped_by_rel


def module_for(path: Path) -> str | None:
    rel = path.relative_to(LEAN_ROOT).with_suffix("").as_posix()
    if rel == "OAI":
        return "OAI"
    if rel.startswith("OAI/") or rel.startswith("ComparatorChallenges/"):
        return rel.replace("/", ".")
    return None


IMPORT_RE = re.compile(r"(?m)^\s*import\s+([^\n]+)$")
MODULE_TOKEN_RE = re.compile(r"[A-Za-z0-9_.'«»-]+")


def imports_from(stripped: str) -> list[str]:
    imports: list[str] = []
    for match in IMPORT_RE.finditer(stripped):
        imports.extend(MODULE_TOKEN_RE.findall(match.group(1)))
    return imports


def import_graph(lean_files: list[Path], stripped_by_rel: dict[str, str]) -> dict[str, Any]:
    module_to_rel: dict[str, str] = {}
    for path in lean_files:
        module = module_for(path)
        if module:
            module_to_rel[module] = path.relative_to(ROOT).as_posix()

    edges: dict[str, list[str]] = {}
    challenge_imports: list[dict[str, str]] = []
    broad_mathlib: list[str] = []
    unresolved_internal: list[dict[str, str]] = []
    for module, rel in sorted(module_to_rel.items()):
        imports = imports_from(stripped_by_rel[rel])
        edges[module] = imports
        if module.startswith("OAI"):
            for imp in imports:
                if imp.startswith("ComparatorChallenges"):
                    challenge_imports.append({"module": module, "import": imp, "path": rel})
                if imp == "Mathlib":
                    broad_mathlib.append(rel)
                if imp.startswith("OAI") and imp not in module_to_rel:
                    unresolved_internal.append({"module": module, "import": imp, "path": rel})

    reachable: set[str] = set()
    stack = ["OAI"] if "OAI" in module_to_rel else []
    while stack:
        module = stack.pop()
        if module in reachable:
            continue
        reachable.add(module)
        for dep in edges.get(module, []):
            if dep in module_to_rel and dep not in reachable:
                stack.append(dep)

    oai_modules = {m for m in module_to_rel if m == "OAI" or m.startswith("OAI.")}
    unreachable = sorted(oai_modules - reachable)
    return {
        "known_module_count": len(module_to_rel),
        "oai_module_count": len(oai_modules),
        "reachable_from_OAI_count": len(reachable & oai_modules),
        "unreachable_from_OAI": unreachable,
        "oai_imports_comparator_challenges": challenge_imports,
        "broad_import_Mathlib_paths": sorted(set(broad_mathlib)),
        "unresolved_internal_imports": unresolved_internal,
    }


def module_path(module: str) -> Path:
    return LEAN_ROOT / (module.replace(".", "/") + ".lean")


def comparator_audit() -> dict[str, Any]:
    directory = LEAN_ROOT / "ComparatorChallenges"
    configs: list[dict[str, Any]] = []
    invalid_json: list[dict[str, str]] = []
    axiom_profiles: collections.Counter[tuple[str, ...]] = collections.Counter()
    nanoda = collections.Counter()
    missing_challenge: list[str] = []
    missing_solution: list[str] = []
    missing_challenge_file_pair: list[str] = []
    declaration_text_unresolved: list[dict[str, str]] = []

    json_files = sorted(directory.glob("*.json"))
    challenge_lean = {p.stem for p in directory.glob("*.lean")}
    for path in json_files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # exact failure is evidence
            invalid_json.append({"path": path.relative_to(ROOT).as_posix(), "error": repr(exc)})
            continue
        challenge = data.get("challenge_module")
        solution = data.get("solution_module")
        theorems = data.get("theorem_names", [])
        definitions = data.get("definition_names", [])
        axioms = tuple(sorted(data.get("permitted_axioms", [])))
        enabled = data.get("enable_nanoda", "missing")
        axiom_profiles[axioms] += 1
        nanoda[str(enabled).lower()] += 1
        if isinstance(challenge, str) and not module_path(challenge).exists():
            missing_challenge.append(path.name)
        if isinstance(solution, str) and not module_path(solution).exists():
            missing_solution.append(path.name)
        if path.stem not in challenge_lean:
            missing_challenge_file_pair.append(path.name)

        solution_text = ""
        if isinstance(solution, str) and module_path(solution).exists():
            solution_text = strip_lean_comments_and_strings(module_path(solution).read_text(encoding="utf-8"))
        for full_name in [*theorems, *definitions]:
            short = str(full_name).split(".")[-1]
            if solution_text and not re.search(
                rf"(?m)^\s*(?:theorem|lemma|def|abbrev|opaque|structure|class|inductive)\s+{re.escape(short)}\b",
                solution_text,
            ):
                declaration_text_unresolved.append({
                    "config": path.name,
                    "solution_module": str(solution),
                    "declaration": str(full_name),
                })
        configs.append({
            "path": path.relative_to(ROOT).as_posix(),
            "challenge_module": challenge,
            "solution_module": solution,
            "theorem_names": theorems,
            "definition_names": definitions,
            "permitted_axioms": list(axioms),
            "enable_nanoda": enabled,
        })

    sorry_challenge_files = []
    no_sorry_challenge_files = []
    for path in sorted(directory.glob("*.lean")):
        stripped = strip_lean_comments_and_strings(path.read_text(encoding="utf-8"))
        target = sorry_challenge_files if re.search(r"\bsorry\b", stripped) else no_sorry_challenge_files
        target.append(path.name)

    return {
        "config_count": len(json_files),
        "challenge_lean_count": len(challenge_lean),
        "invalid_json": invalid_json,
        "nanoda_profile": dict(sorted(nanoda.items())),
        "permitted_axiom_profiles": [
            {"axioms": list(profile), "count": count}
            for profile, count in axiom_profiles.most_common()
        ],
        "missing_challenge_modules": sorted(missing_challenge),
        "missing_solution_modules": sorted(missing_solution),
        "configs_without_same_stem_challenge_file": sorted(missing_challenge_file_pair),
        "challenge_files_with_sorry_count": len(sorry_challenge_files),
        "challenge_files_without_sorry": no_sorry_challenge_files,
        "declaration_text_unresolved": declaration_text_unresolved,
        "configs": configs,
    }


def lake_audit(tracked: list[Path]) -> dict[str, Any]:
    lakefile = LEAN_ROOT / "lakefile.lean"
    text = lakefile.read_text(encoding="utf-8")
    require_re = re.compile(
        r"(?m)^require\s+([^\s]+)\s+from\s+git\s*\n\s*\"([^\"]+)\"\s*@\s*\"([^\"]+)\""
    )
    requirements = [
        {"name": m.group(1), "url": m.group(2), "revision": m.group(3), "full_commit": bool(re.fullmatch(r"[0-9a-f]{40}", m.group(3)))}
        for m in require_re.finditer(text)
    ]
    moving_requirements = [r for r in requirements if not r["full_commit"]]

    patch_files = sorted((LEAN_ROOT / "patches").glob("*.patch"))
    patches = [
        {
            "path": p.relative_to(ROOT).as_posix(),
            "bytes": p.stat().st_size,
            "sha256": sha256_file(p),
            "dependency_prefix": p.name.removesuffix("-lean4341.patch"),
        }
        for p in patch_files
    ]
    requirement_names = {r["name"].strip("«»") for r in requirements}
    orphan_patch_prefixes = sorted({p["dependency_prefix"] for p in patches} - requirement_names)

    risk_tokens = [
        "run_cmd", "post_update", "IO.Process", "git", "apply", "clone",
        "unsafe env.evalConstCheck", ".lake/packages",
    ]
    present = {token: text.count(token) for token in risk_tokens if token in text}

    manifest_path = LEAN_ROOT / "lake-manifest.json"
    manifest: dict[str, Any] = {}
    manifest_error = None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        manifest_error = repr(exc)
    packages = manifest.get("packages", []) if isinstance(manifest, dict) else []
    manifest_records: list[dict[str, Any]] = []
    moving_manifest_refs: list[dict[str, Any]] = []
    for package in packages if isinstance(packages, list) else []:
        if not isinstance(package, dict):
            continue
        record = {
            "name": package.get("name"),
            "url": package.get("url"),
            "rev": package.get("rev"),
            "inputRev": package.get("inputRev"),
            "type": package.get("type"),
        }
        manifest_records.append(record)
        rev = package.get("rev")
        if package.get("type") == "git" and (not isinstance(rev, str) or not re.fullmatch(r"[0-9a-f]{40}", rev)):
            moving_manifest_refs.append(record)

    return {
        "lakefile_sha256": sha256_file(lakefile),
        "requirement_count": len(requirements),
        "requirements": requirements,
        "moving_lakefile_requirements": moving_requirements,
        "patch_count": len(patches),
        "patch_total_bytes": sum(p["bytes"] for p in patches),
        "patches": patches,
        "orphan_patch_prefixes": orphan_patch_prefixes,
        "configuration_execution_signals": present,
        "manifest_sha256": sha256_file(manifest_path),
        "manifest_parse_error": manifest_error,
        "manifest_package_count": len(manifest_records),
        "manifest_packages": manifest_records,
        "moving_manifest_refs": moving_manifest_refs,
    }


def duplicate_files(files: Iterable[Path]) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = collections.defaultdict(list)
    for path in files:
        digest = sha256_file(path)
        groups[digest].append(path.relative_to(ROOT).as_posix())
    return [
        {"sha256": digest, "paths": paths}
        for digest, paths in sorted(groups.items())
        if len(paths) > 1
    ]


def provenance_headers(oai_files: list[Path]) -> dict[str, Any]:
    adapted: list[dict[str, Any]] = []
    authors_header: list[str] = []
    copyright_header: list[str] = []
    for path in oai_files:
        rel = path.relative_to(ROOT).as_posix()
        head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:100])
        if re.search(r"adapted\s+from|modified\s+from|ported\s+from", head, re.I):
            adapted.append({"path": rel, "sha256": sha256_file(path)})
        if re.search(r"(?mi)^\s*(?:authors?|author)\s*:", head):
            authors_header.append(rel)
        if re.search(r"(?mi)copyright\s*\(c\)", head):
            copyright_header.append(rel)
    return {
        "adaptation_header_files": adapted,
        "author_header_file_count": len(authors_header),
        "copyright_header_file_count": len(copyright_header),
        "author_header_files": sorted(authors_header),
    }


def markdown_report(report: dict[str, Any]) -> str:
    token_summary = report["source_scan"]["token_summary"]
    import_info = report["imports"]
    comparator = report["comparator"]
    lake = report["lake"]
    violations = report["policy_violations"]
    review = report["review_signals"]

    lines = [
        "# Genesis rigor scan",
        "",
        f"- Commit: `{report['git']['commit']}`",
        f"- Tree: `{report['git']['tree']}`",
        f"- Scanner SHA-256: `{report['scanner']['sha256']}`",
        f"- Tracked files: **{report['git']['tracked_file_count']:,}**",
        f"- Lean files: **{report['source_scan']['lean_file_count']:,}**",
        "",
        "## High-confidence policy violations",
        "",
    ]
    if violations:
        lines.extend(f"- **{v['code']}**: {v['detail']}" for v in violations)
    else:
        lines.append("- None detected by this static scanner.")

    lines += ["", "## Principal review signals", ""]
    lines.extend(f"- **{r['code']}**: {r['detail']}" for r in review)

    lines += [
        "",
        "## Source-token observations",
        "",
        "| Token | Challenge | Solution | Other | Total |",
        "|---|---:|---:|---:|---:|",
    ]
    for token, counts in sorted(token_summary.items()):
        lines.append(
            f"| `{token}` | {counts.get('challenge', 0)} | {counts.get('solution', 0)} | "
            f"{counts.get('other', 0) + counts.get('scope_doc', 0) + counts.get('patch', 0)} | {counts.get('total', 0)} |"
        )

    lines += [
        "",
        "## Comparator surface",
        "",
        f"- JSON configurations: **{comparator['config_count']}**",
        f"- Challenge Lean files: **{comparator['challenge_lean_count']}**",
        f"- Challenge files with actual `sorry`: **{comparator['challenge_files_with_sorry_count']}**",
        f"- `enable_nanoda` profile: `{json.dumps(comparator['nanoda_profile'], sort_keys=True)}`",
        f"- Missing challenge modules: **{len(comparator['missing_challenge_modules'])}**",
        f"- Missing solution modules: **{len(comparator['missing_solution_modules'])}**",
        f"- Lexically unresolved named declarations: **{len(comparator['declaration_text_unresolved'])}**",
        "",
        "## Import graph",
        "",
        f"- OAI modules: **{import_info['oai_module_count']}**",
        f"- Reachable from `OAI.lean`: **{import_info['reachable_from_OAI_count']}**",
        f"- Not reachable from `OAI.lean`: **{len(import_info['unreachable_from_OAI'])}**",
        f"- OAI imports of Comparator challenges: **{len(import_info['oai_imports_comparator_challenges'])}**",
        f"- Exact broad `import Mathlib` files: **{len(import_info['broad_import_Mathlib_paths'])}**",
        f"- Unresolved internal OAI imports: **{len(import_info['unresolved_internal_imports'])}**",
        "",
        "## Lake and dependency transformation",
        "",
        f"- Direct Git requirements parsed: **{lake['requirement_count']}**",
        f"- Non-full-commit requirements: **{len(lake['moving_lakefile_requirements'])}**",
        f"- Compatibility patches: **{lake['patch_count']}**",
        f"- Patch bytes: **{lake['patch_total_bytes']:,}**",
        f"- Manifest packages: **{lake['manifest_package_count']}**",
        f"- Moving manifest refs: **{len(lake['moving_manifest_refs'])}**",
        f"- Configuration execution signals: `{json.dumps(lake['configuration_execution_signals'], sort_keys=True)}`",
        "",
        "## Scope",
        "",
        "This is a deterministic static scan. It does not replace Lean elaboration, `#print axioms`, Comparator replay, independent-kernel checking, mathematical peer review, or manuscript-to-statement comparison.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    tracked = tracked_files()
    lean_files = sorted(p for p in tracked if p.suffix == ".lean")
    oai_files = [p for p in lean_files if p.relative_to(ROOT).as_posix().startswith("lean/OAI/")]
    findings, stripped = source_findings(lean_files)

    summary: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for finding in findings:
        summary[finding.token][finding.path_class] += 1
        summary[finding.token]["total"] += 1
    token_summary = {token: dict(counts) for token, counts in sorted(summary.items())}

    imports = import_graph(lean_files, stripped)
    comparator = comparator_audit()
    lake = lake_audit(tracked)
    modes = git_modes()
    symlinks = sorted(path for path, mode in modes.items() if mode == "120000")
    submodules = sorted(path for path, mode in modes.items() if mode == "160000")

    violations: list[dict[str, str]] = []
    solution_sorry = [f for f in findings if f.path_class == "solution" and f.token in {"sorry", "admit"}]
    if solution_sorry:
        violations.append({"code": "SOLUTION_PLACEHOLDER", "detail": f"{len(solution_sorry)} actual `sorry`/`admit` tokens occur in the OAI solution tree."})
    if imports["oai_imports_comparator_challenges"]:
        violations.append({"code": "CHALLENGE_IMPORT", "detail": f"{len(imports['oai_imports_comparator_challenges'])} OAI modules import ComparatorChallenges."})
    if comparator["missing_solution_modules"] or comparator["missing_challenge_modules"]:
        violations.append({"code": "BROKEN_COMPARATOR_MODULE", "detail": "One or more Comparator configurations reference a missing challenge or solution module."})
    if lake["moving_lakefile_requirements"] or lake["moving_manifest_refs"]:
        violations.append({"code": "MOVING_DEPENDENCY", "detail": "At least one Git dependency is not frozen to a full commit."})

    review: list[dict[str, str]] = []
    if lake["patch_count"]:
        review.append({"code": "PATCHED_DEPENDENCY_TREE", "detail": f"{lake['patch_count']} compatibility patches ({lake['patch_total_bytes']:,} bytes) mutate dependency checkouts; effective source identity must include the ordered patch set."})
    true_nanoda = int(comparator["nanoda_profile"].get("true", 0))
    review.append({"code": "INDEPENDENT_KERNEL_COVERAGE", "detail": f"Only {true_nanoda} of {comparator['config_count']} Comparator configurations declare `enable_nanoda: true`; all others require an explicit independent-kernel status."})
    if imports["unreachable_from_OAI"]:
        review.append({"code": "ROOT_REACHABILITY", "detail": f"{len(imports['unreachable_from_OAI'])} OAI modules are not lexically reachable from `OAI.lean`; they need intended-root or orphan classification."})
    if imports["broad_import_Mathlib_paths"]:
        review.append({"code": "BROAD_IMPORT", "detail": f"{len(imports['broad_import_Mathlib_paths'])} OAI files use exact `import Mathlib`, enlarging ambient dependency and elaboration surfaces."})
    run_tac_count = token_summary.get("run_tac", {}).get("solution", 0)
    if run_tac_count:
        review.append({"code": "METAPROGRAMMED_PROOF", "detail": f"{run_tac_count} `run_tac` occurrences appear in solution source and require exact-toolchain replay."})
    local_instance_count = token_summary.get("local_instance", {}).get("solution", 0) + token_summary.get("local_instance_attribute", {}).get("solution", 0)
    if local_instance_count:
        review.append({"code": "ELABORATION_CONTEXT", "detail": f"{local_instance_count} local-instance declarations/attributes alter typeclass search and should be captured in theorem receipts."})
    if comparator["declaration_text_unresolved"]:
        review.append({"code": "CONFIG_DECLARATION_RESOLUTION", "detail": f"{len(comparator['declaration_text_unresolved'])} configured declarations were not located by the conservative lexical resolver and require Lean-environment resolution."})

    report: dict[str, Any] = {
        "schema": "GenesisRigorScan/1",
        "git": {
            "commit": run("git", "rev-parse", "HEAD"),
            "tree": run("git", "rev-parse", "HEAD^{tree}"),
            "tracked_file_count": len(tracked),
            "symlinks": symlinks,
            "submodules": submodules,
        },
        "scanner": {
            "path": Path(__file__).relative_to(ROOT).as_posix(),
            "sha256": sha256_file(Path(__file__)),
            "python": sys.version,
        },
        "source_scan": {
            "lean_file_count": len(lean_files),
            "oai_file_count": len(oai_files),
            "token_summary": token_summary,
            "findings": [asdict(f) for f in findings],
        },
        "imports": imports,
        "comparator": comparator,
        "lake": lake,
        "provenance_headers": provenance_headers(oai_files),
        "duplicate_oai_files": duplicate_files(oai_files),
        "policy_violations": violations,
        "review_signals": review,
        "limitations": [
            "Lexical scanning is not Lean parsing or elaboration.",
            "Declaration-name resolution is conservative and can miss generated or namespaced syntax.",
            "Import reachability is lexical and does not model generated imports.",
            "No theorem correctness, originality, priority, or authorship conclusion follows from this report alone.",
        ],
    }

    json_path = OUT / "genesis-rigor-scan.json"
    md_path = OUT / "genesis-rigor-scan.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    print(md_path.read_text(encoding="utf-8"))
    print(f"JSON_SHA256={sha256_file(json_path)}")
    print(f"MARKDOWN_SHA256={sha256_file(md_path)}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
