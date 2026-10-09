#!/usr/bin/env python3
"""Generate bounded, deterministic static closure receipts for selected theorems.

This scanner is intentionally narrower than a whole-corpus lexical scan.  It
walks only the transitive local import closures of named theorem roots, records
the ambient elaboration surface visible in source, and compares selected proof
routes.  It does not elaborate Lean and is not a mathematical correctness
certificate.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

BASE_REV = "fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb"

ROOT = Path(__file__).resolve().parents[2]
LEAN_ROOT = ROOT / "lean"
RESULT_ROOT = ROOT / "audit" / "results" / "theorem-closure"

INTERNAL_PREFIXES = ("OAI", "ComparatorChallenges")

APPROVED_FOUNDATIONAL_AXIOMS = {
    "propext",
    "Quot.sound",
    "Classical.choice",
}


@dataclass(frozen=True)
class TargetSpec:
    key: str
    label: str
    root_module: str
    theorem_names: tuple[str, ...]
    comparator_config: str
    challenge_module: str


TARGETS: tuple[TargetSpec, ...] = (
    TargetSpec(
        key="quasi_riemann_zeta",
        label="Riemann zeta zero-free half-plane Re(s) > 7/8",
        root_module="OAI.NumberTheory.DirichletL.Nonvanishing",
        theorem_names=("OAI.riemannZeta_ne_zero_of_seven_eighths_lt_re",),
        comparator_config="ComparatorChallenges/QuasiRiemannHypothesis.json",
        challenge_module="ComparatorChallenges.QuasiRiemannHypothesis",
    ),
    TargetSpec(
        key="landau_siegel_geometric",
        label="Uniform Landau-Siegel gap — geometric/Bezout route",
        root_module="OAI.NumberTheory.SiegelZeros.Conclusions.Theorem",
        theorem_names=(
            "OAI.SiegelZeros.WeightedTorusJets.exists_absolute_real_zero_gap",
        ),
        comparator_config="ComparatorChallenges/SiegelZeros.json",
        challenge_module="ComparatorChallenges.SiegelZeros",
    ),
    TargetSpec(
        key="landau_siegel_analytic",
        label="Uniform Landau-Siegel gap — analytic/contrary-sequence route",
        root_module=(
            "OAI.NumberTheory.SiegelZeros.Characters."
            "DirichletRealZeroBoundProof"
        ),
        theorem_names=(
            "OAI.SiegelZeros.WeightedTorusJets.dirichletRealZeroBound_proof",
        ),
        comparator_config="ComparatorChallenges/SiegelZeros.json",
        challenge_module="ComparatorChallenges.SiegelZeros",
    ),
)


@dataclass(frozen=True)
class Finding:
    severity: str
    category: str
    module: str
    path: str
    line: int
    symbol: str
    snippet: str
    note: str = ""


@dataclass(frozen=True)
class SourceRegion:
    theorem: str
    module: str
    path: str
    start_line: int
    end_line: int
    source_sha256: str
    region_sha256: str
    normalized_statement_sha256: str
    normalized_statement: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_git(*args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc.stdout.strip()


def module_to_path(module: str, lean_root: Path = LEAN_ROOT) -> Path:
    """Map a Lean module name to its exact source path without ASCII folding."""
    return lean_root / (module.replace(".", "/") + ".lean")


def strip_lean_comments_and_strings(text: str) -> str:
    """Blank comments and strings while preserving byte-shape at codepoint level.

    Nested block comments, line comments, ordinary strings, and Lean raw
    strings are supported.  Newlines and total string length are preserved so
    offsets remain valid for line reporting.
    """

    out: list[str] = []
    i = 0
    n = len(text)
    block_depth = 0
    line_comment = False
    in_string = False
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

        if in_string:
            if c == "\\" and i + 1 < n:
                out.extend("  ")
                i += 2
            elif c == '"':
                in_string = False
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

        raw = re.match(r'r(#+)?"', text[i:])
        if raw:
            token = raw.group(0)
            raw_hashes = raw.group(1) or ""
            out.extend(" " * len(token))
            i += len(token)
            continue

        if c == '"':
            in_string = True
            out.append(" ")
            i += 1
            continue

        out.append(c)
        i += 1

    return "".join(out)


IMPORT_RE = re.compile(
    r"^\s*(?:(?:public|private)\s+)?import(?:\s+(.*?))?\s*$"
)


def parse_imports(text: str) -> tuple[list[str], list[int]]:
    """Return imported module tokens and lines with an unparsed empty import."""
    stripped = strip_lean_comments_and_strings(text)
    modules: list[str] = []
    unparsed_lines: list[int] = []
    for line_no, line in enumerate(stripped.splitlines(), 1):
        match = IMPORT_RE.match(line)
        if not match:
            continue
        payload = (match.group(1) or "").strip()
        if not payload:
            unparsed_lines.append(line_no)
            continue
        modules.extend(payload.split())
    return modules, unparsed_lines


DECLARATION_RE = re.compile(
    r"^\s*(?:(?:private|protected|noncomputable|local)\s+)*"
    r"(theorem|lemma|def|abbrev|opaque|axiom)\s+([^\s:({]+)"
)


def short_name(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def extract_source_region(
    *,
    theorem: str,
    module: str,
    path: Path,
    raw: str,
) -> SourceRegion | None:
    """Extract a declaration header through its first source-level ':=' token."""
    wanted = short_name(theorem)
    raw_lines = raw.splitlines()
    stripped_lines = strip_lean_comments_and_strings(raw).splitlines()

    start_index: int | None = None
    for index, line in enumerate(stripped_lines):
        match = DECLARATION_RE.match(line)
        if match and short_name(match.group(2)) == wanted:
            start_index = index
            break

    if start_index is None:
        return None

    end_index = start_index
    collected: list[str] = []
    found_assignment = False
    for index in range(start_index, len(stripped_lines)):
        stripped_line = stripped_lines[index]
        raw_line = raw_lines[index] if index < len(raw_lines) else ""
        assignment_at = stripped_line.find(":=")
        if assignment_at >= 0:
            collected.append(raw_line[:assignment_at].rstrip())
            end_index = index
            found_assignment = True
            break
        collected.append(raw_line)
        end_index = index
        if index - start_index > 400:
            break

    if not found_assignment:
        return None

    region_text = "\n".join(raw_lines[start_index : end_index + 1]) + "\n"
    statement_text = "\n".join(collected).strip()
    normalized = " ".join(statement_text.split())
    return SourceRegion(
        theorem=theorem,
        module=module,
        path=str(path.relative_to(ROOT)),
        start_line=start_index + 1,
        end_line=end_index + 1,
        source_sha256=sha256_bytes(raw.encode("utf-8")),
        region_sha256=sha256_bytes(region_text.encode("utf-8")),
        normalized_statement_sha256=sha256_bytes(normalized.encode("utf-8")),
        normalized_statement=normalized,
    )


def is_internal_module(module: str) -> bool:
    return module == INTERNAL_PREFIXES[0] or module == INTERNAL_PREFIXES[1] or any(
        module.startswith(prefix + ".") for prefix in INTERNAL_PREFIXES
    )


def collect_closure(
    root_module: str,
    *,
    lean_root: Path = LEAN_ROOT,
) -> dict[str, Any]:
    queue: deque[str] = deque([root_module])
    seen: set[str] = set()
    edges: dict[str, list[str]] = {}
    external_imports: set[str] = set()
    missing_internal: list[dict[str, str]] = []
    unparsed_imports: list[dict[str, Any]] = []
    source_paths: dict[str, Path] = {}

    while queue:
        module = queue.popleft()
        if module in seen:
            continue
        seen.add(module)
        path = module_to_path(module, lean_root)
        if not path.exists():
            if is_internal_module(module):
                missing_internal.append(
                    {"source": "<root-or-transitive>", "module": module}
                )
            else:
                external_imports.add(module)
            continue

        source_paths[module] = path
        raw = path.read_text(encoding="utf-8")
        imports, empty_lines = parse_imports(raw)
        edges[module] = sorted(set(imports))
        for line in empty_lines:
            unparsed_imports.append(
                {
                    "module": module,
                    "path": str(path),
                    "line": line,
                    "kind": "empty_or_multiline_import",
                }
            )

        for imported in imports:
            imported_path = module_to_path(imported, lean_root)
            if imported_path.exists():
                if imported not in seen:
                    queue.append(imported)
            elif is_internal_module(imported):
                missing_internal.append({"source": module, "module": imported})
            else:
                external_imports.add(imported)

    return {
        "root_module": root_module,
        "modules": sorted(source_paths),
        "source_paths": source_paths,
        "edges": edges,
        "external_imports": sorted(external_imports),
        "missing_internal_imports": sorted(
            missing_internal, key=lambda x: (x["source"], x["module"])
        ),
        "unparsed_imports": sorted(
            unparsed_imports,
            key=lambda x: (x["module"], x["line"]),
        ),
    }


TOKEN_SPECS: tuple[tuple[str, str, re.Pattern[str], str], ...] = (
    (
        "critical",
        "sorry_token",
        re.compile(r"\bsorry\b"),
        "Proof placeholder outside comments and strings.",
    ),
    (
        "critical",
        "admit_token",
        re.compile(r"\badmit\b"),
        "Proof placeholder outside comments and strings.",
    ),
    (
        "critical",
        "sorryAx_reference",
        re.compile(r"\bsorryAx\b"),
        "Direct reference to Lean's placeholder axiom.",
    ),
    (
        "critical",
        "implemented_by",
        re.compile(r"\bimplemented_by\b"),
        "Alternative executable implementation must not replace proof evidence.",
    ),
    (
        "high",
        "unsafe_token",
        re.compile(r"\bunsafe\b"),
        "Unsafe declarations require exact theorem-level review.",
    ),
    (
        "high",
        "native_decide",
        re.compile(r"\bnative_decide\b"),
        "Native computation expands the trusted execution surface.",
    ),
    (
        "medium",
        "exact_decide",
        re.compile(r"\bexact_decide\b"),
        "Decision-procedure use should be retained in the receipt.",
    ),
    (
        "medium",
        "run_tac",
        re.compile(r"\brun_tac\b"),
        "Metaprogrammed proof generation requires exact-toolchain replay.",
    ),
    (
        "medium",
        "lean_elab_api",
        re.compile(r"\bLean\.(?:Elab|Meta|Core)\b"),
        "Direct elaborator/metaprogramming API use.",
    ),
    (
        "review",
        "False.elim",
        re.compile(r"\bFalse\.elim\b"),
        "Trace the contradiction provider and intended model.",
    ),
    (
        "review",
        "Subsingleton.elim",
        re.compile(r"\bSubsingleton\.elim\b"),
        "Record the exact subsingleton instance and semantic intent.",
    ),
)

OPTION_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "medium",
        "autoImplicit_true",
        re.compile(r"^\s*set_option\s+autoImplicit\s+true\b"),
    ),
    (
        "review",
        "maxHeartbeats",
        re.compile(r"^\s*set_option\s+maxHeartbeats\s+([^\s]+)"),
    ),
    (
        "review",
        "maxRecDepth",
        re.compile(r"^\s*set_option\s+maxRecDepth\s+([^\s]+)"),
    ),
    (
        "medium",
        "warningAsError_false",
        re.compile(r"^\s*set_option\s+warningAsError\s+false\b"),
    ),
)

DECLARATION_PATTERNS: tuple[tuple[str, str, re.Pattern[str], str], ...] = (
    (
        "critical",
        "axiom_declaration",
        re.compile(
            r"^\s*(?:(?:private|protected)\s+)*axiom\s+([^\s:({]+)"
        ),
        "Explicit local axiom in a solution closure.",
    ),
    (
        "review",
        "opaque_declaration",
        re.compile(
            r"^\s*(?:(?:private|protected|noncomputable)\s+)*"
            r"opaque\s+([^\s:({]+)"
        ),
        "Kernel-checked opaque body; retain body identity and reduction API.",
    ),
    (
        "critical",
        "extern_declaration",
        re.compile(r"^\s*(?:@\[[^\]]*\]\s*)*extern\s+([^\s:({]+)"),
        "Foreign implementation declaration in a theorem closure.",
    ),
)


def make_finding(
    *,
    severity: str,
    category: str,
    module: str,
    path: Path,
    line_no: int,
    symbol: str,
    snippet: str,
    note: str,
) -> Finding:
    try:
        rel = str(path.relative_to(ROOT))
    except ValueError:
        rel = str(path)
    return Finding(
        severity=severity,
        category=category,
        module=module,
        path=rel,
        line=line_no,
        symbol=symbol[:240],
        snippet=snippet.strip()[:500],
        note=note,
    )


def scan_source(
    *,
    module: str,
    path: Path,
    raw: str,
    imports: Iterable[str],
) -> tuple[list[Finding], dict[str, Any]]:
    stripped = strip_lean_comments_and_strings(raw)
    raw_lines = raw.splitlines()
    stripped_lines = stripped.splitlines()
    findings: list[Finding] = []
    counts: Counter[str] = Counter()

    for imported in imports:
        if module.startswith("OAI") and imported.startswith("ComparatorChallenges"):
            findings.append(
                make_finding(
                    severity="critical",
                    category="challenge_imported_by_solution",
                    module=module,
                    path=path,
                    line_no=1,
                    symbol=imported,
                    snippet=f"import {imported}",
                    note="A solution closure must not import a challenge placeholder.",
                )
            )

    if any(imported == "Mathlib" for imported in imports):
        counts["exact_import_Mathlib"] += 1

    for line_no, (raw_line, stripped_line) in enumerate(
        zip(raw_lines, stripped_lines, strict=False), 1
    ):
        for severity, category, pattern, note in DECLARATION_PATTERNS:
            match = pattern.search(stripped_line)
            if match:
                findings.append(
                    make_finding(
                        severity=severity,
                        category=category,
                        module=module,
                        path=path,
                        line_no=line_no,
                        symbol=match.group(1),
                        snippet=raw_line,
                        note=note,
                    )
                )

        for severity, category, pattern, note in TOKEN_SPECS:
            for match in pattern.finditer(stripped_line):
                findings.append(
                    make_finding(
                        severity=severity,
                        category=category,
                        module=module,
                        path=path,
                        line_no=line_no,
                        symbol=match.group(0),
                        snippet=raw_line,
                        note=note,
                    )
                )

        for severity, category, pattern in OPTION_PATTERNS:
            match = pattern.search(stripped_line)
            if match:
                symbol = match.group(1) if match.lastindex else match.group(0)
                findings.append(
                    make_finding(
                        severity=severity,
                        category=category,
                        module=module,
                        path=path,
                        line_no=line_no,
                        symbol=symbol,
                        snippet=raw_line,
                        note="Elaboration or resource option in the theorem closure.",
                    )
                )

        if re.search(r"^\s*(?:local\s+)?instance\b", stripped_line):
            counts["local_instance_declarations"] += 1
        if re.search(
            r"^\s*attribute\s+\[local\s+instance(?:\s+[^\]]*)?\]",
            stripped_line,
        ):
            counts["local_instance_attributes"] += 1
        if re.search(r"^\s*open\s+scoped\b", stripped_line):
            counts["open_scoped_commands"] += 1
        if re.search(r"^\s*open\b", stripped_line):
            counts["open_commands"] += 1
        if re.search(r"^\s*local\s+notation\b", stripped_line):
            counts["local_notations"] += 1

    declaration_names: list[str] = []
    for line in stripped_lines:
        match = DECLARATION_RE.match(line)
        if match:
            declaration_names.append(match.group(2))

    return findings, {
        "sha256": sha256_bytes(raw.encode("utf-8")),
        "bytes": len(raw.encode("utf-8")),
        "line_count": len(raw_lines),
        "imports": sorted(set(imports)),
        "declaration_names": sorted(set(declaration_names)),
        **dict(sorted(counts.items())),
    }


def inspect_comparator_config(spec: TargetSpec) -> dict[str, Any]:
    path = LEAN_ROOT / spec.comparator_config
    result: dict[str, Any] = {
        "path": str(path.relative_to(ROOT)),
        "exists": path.exists(),
    }
    if not path.exists():
        result["problems"] = ["missing_comparator_config"]
        return result

    raw = path.read_bytes()
    result["sha256"] = sha256_bytes(raw)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        result["problems"] = [f"invalid_json: {exc}"]
        return result

    problems: list[str] = []
    challenge = data.get("challenge_module")
    solution = data.get("solution_module")
    theorem_names = data.get("theorem_names", [])
    permitted_axioms = data.get("permitted_axioms", [])
    if challenge != spec.challenge_module:
        problems.append(
            f"challenge_module_mismatch: expected {spec.challenge_module!r}, "
            f"observed {challenge!r}"
        )
    if solution != spec.root_module:
        problems.append(
            f"solution_module_mismatch: expected {spec.root_module!r}, "
            f"observed {solution!r}"
        )
    for theorem in spec.theorem_names:
        if theorem not in theorem_names:
            problems.append(f"target_not_listed: {theorem}")
    unexpected = sorted(set(permitted_axioms) - APPROVED_FOUNDATIONAL_AXIOMS)
    if unexpected:
        problems.append(f"unexpected_permitted_axioms: {unexpected}")

    result.update(
        {
            "challenge_module": challenge,
            "solution_module": solution,
            "theorem_names": theorem_names,
            "definition_names": data.get("definition_names", []),
            "permitted_axioms": permitted_axioms,
            "enable_nanoda": data.get("enable_nanoda", "<absent>"),
            "problems": problems,
        }
    )
    return result


def inspect_challenge(spec: TargetSpec) -> dict[str, Any]:
    path = module_to_path(spec.challenge_module)
    result: dict[str, Any] = {
        "module": spec.challenge_module,
        "path": str(path.relative_to(ROOT)),
        "exists": path.exists(),
        "classification": "CHALLENGE_STATEMENT_ONLY",
    }
    if not path.exists():
        result["problems"] = ["missing_challenge_module"]
        return result

    raw = path.read_text(encoding="utf-8")
    imports, unparsed = parse_imports(raw)
    findings, source = scan_source(
        module=spec.challenge_module,
        path=path,
        raw=raw,
        imports=imports,
    )
    regions = []
    for theorem in spec.theorem_names:
        region = extract_source_region(
            theorem=theorem,
            module=spec.challenge_module,
            path=path,
            raw=raw,
        )
        if region:
            regions.append(asdict(region))

    result.update(
        {
            "source": source,
            "unparsed_import_lines": unparsed,
            "placeholder_findings": [
                asdict(f)
                for f in findings
                if f.category
                in {
                    "sorry_token",
                    "admit_token",
                    "sorryAx_reference",
                    "axiom_declaration",
                }
            ],
            "target_regions": regions,
        }
    )
    return result


def build_target_receipt(spec: TargetSpec) -> dict[str, Any]:
    closure = collect_closure(spec.root_module)
    source_paths: dict[str, Path] = closure.pop("source_paths")
    findings: list[Finding] = []
    files: dict[str, Any] = {}
    regions: list[dict[str, Any]] = []
    total_bytes = 0

    for module in sorted(source_paths):
        path = source_paths[module]
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            findings.append(
                make_finding(
                    severity="critical",
                    category="invalid_utf8",
                    module=module,
                    path=path,
                    line_no=1,
                    symbol="UTF-8",
                    snippet="",
                    note=str(exc),
                )
            )
            continue

        imports = closure["edges"].get(module, [])
        file_findings, source_info = scan_source(
            module=module,
            path=path,
            raw=raw,
            imports=imports,
        )
        findings.extend(file_findings)
        files[module] = {
            "path": str(path.relative_to(ROOT)),
            **source_info,
        }
        total_bytes += source_info["bytes"]

        for theorem in spec.theorem_names:
            region = extract_source_region(
                theorem=theorem,
                module=module,
                path=path,
                raw=raw,
            )
            if region is not None:
                regions.append(asdict(region))

    for missing in closure["missing_internal_imports"]:
        findings.append(
            Finding(
                severity="critical",
                category="missing_internal_import",
                module=missing["source"],
                path="<unresolved>",
                line=0,
                symbol=missing["module"],
                snippet="",
                note="An internal OAI/Comparator module could not be resolved.",
            )
        )

    for item in closure["unparsed_imports"]:
        findings.append(
            Finding(
                severity="high",
                category="unparsed_import_command",
                module=item["module"],
                path=item["path"],
                line=item["line"],
                symbol=item["kind"],
                snippet="",
                note="Import grammar requires Lean-parser confirmation.",
            )
        )

    located = {r["theorem"] for r in regions}
    for theorem in spec.theorem_names:
        if theorem not in located:
            findings.append(
                Finding(
                    severity="critical",
                    category="target_declaration_not_located",
                    module=spec.root_module,
                    path=str(module_to_path(spec.root_module).relative_to(ROOT)),
                    line=0,
                    symbol=theorem,
                    snippet="",
                    note="The configured target was not lexically located in its closure.",
                )
            )

    by_category = Counter(f.category for f in findings)
    by_severity = Counter(f.severity for f in findings)
    critical = [f for f in findings if f.severity == "critical"]

    root_path = module_to_path(spec.root_module)
    root_imports = (
        closure["edges"].get(spec.root_module, []) if root_path.exists() else []
    )

    return {
        "key": spec.key,
        "label": spec.label,
        "root_module": spec.root_module,
        "root_path": str(root_path.relative_to(ROOT)),
        "theorem_names": list(spec.theorem_names),
        "module_count": len(files),
        "source_bytes": total_bytes,
        "root_direct_imports": root_imports,
        "modules": sorted(files),
        "files": files,
        "edges": closure["edges"],
        "external_imports": closure["external_imports"],
        "missing_internal_imports": closure["missing_internal_imports"],
        "unparsed_imports": closure["unparsed_imports"],
        "target_regions": sorted(
            regions, key=lambda x: (x["theorem"], x["path"], x["start_line"])
        ),
        "finding_counts_by_category": dict(sorted(by_category.items())),
        "finding_counts_by_severity": dict(sorted(by_severity.items())),
        "findings": [
            asdict(f)
            for f in sorted(
                findings,
                key=lambda x: (
                    x.severity,
                    x.category,
                    x.path,
                    x.line,
                    x.symbol,
                ),
            )
        ],
        "critical_policy_violation_count": len(critical),
        "comparator": inspect_comparator_config(spec),
        "challenge": inspect_challenge(spec),
    }


def compare_routes(targets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    geometric = set(targets["landau_siegel_geometric"]["modules"])
    analytic = set(targets["landau_siegel_analytic"]["modules"])
    shared = geometric & analytic
    union = geometric | analytic
    geometric_root = targets["landau_siegel_geometric"]["root_module"]
    analytic_root = targets["landau_siegel_analytic"]["root_module"]

    return {
        "pair": [
            "landau_siegel_geometric",
            "landau_siegel_analytic",
        ],
        "geometric_module_count": len(geometric),
        "analytic_module_count": len(analytic),
        "shared_module_count": len(shared),
        "geometric_unique_module_count": len(geometric - analytic),
        "analytic_unique_module_count": len(analytic - geometric),
        "jaccard_module_overlap": (len(shared) / len(union)) if union else 1.0,
        "geometric_imports_analytic_root": analytic_root in geometric,
        "analytic_imports_geometric_root": geometric_root in analytic,
        "shared_modules": sorted(shared),
        "geometric_unique_modules": sorted(geometric - analytic),
        "analytic_unique_modules": sorted(analytic - geometric),
        "interpretation": (
            "Static import overlap only.  This does not establish causal or "
            "mathematical independence."
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Bounded theorem-closure receipts",
        "",
        f"- Frozen upstream base: `{report['audit_identity']['base_revision']}`",
        f"- Audit head: `{report['audit_identity']['head_commit']}`",
        f"- Audit tree: `{report['audit_identity']['head_tree']}`",
        f"- Scanner SHA-256: `{report['audit_identity']['scanner_sha256']}`",
        "",
        "> Static source and import-closure audit only. This is not Lean",
        "> elaboration, kernel replay, Comparator replay, statement-equivalence",
        "> certification, mathematical peer review, or an independence proof.",
        "",
        "## Target summaries",
        "",
        "| Target | Modules | Source bytes | Critical policy findings | External import roots |",
        "|---|---:|---:|---:|---:|",
    ]

    for key, target in report["targets"].items():
        lines.append(
            f"| `{key}` | {target['module_count']:,} | "
            f"{target['source_bytes']:,} | "
            f"{target['critical_policy_violation_count']:,} | "
            f"{len(target['external_imports']):,} |"
        )

    lines += [
        "",
        "## Exact configured statement regions",
        "",
    ]
    for key, target in report["targets"].items():
        lines.append(f"### `{key}`")
        lines.append("")
        if not target["target_regions"]:
            lines.append("- Target declaration was not located.")
        else:
            for region in target["target_regions"]:
                lines.append(
                    f"- `{region['theorem']}` — `{region['path']}:"
                    f"{region['start_line']}-{region['end_line']}` — "
                    f"statement SHA-256 `{region['normalized_statement_sha256']}`"
                )
        lines.append("")

    route = report["route_comparison"]
    lines += [
        "## Landau–Siegel route overlap",
        "",
        f"- Geometric closure: **{route['geometric_module_count']:,}** modules",
        f"- Analytic closure: **{route['analytic_module_count']:,}** modules",
        f"- Shared: **{route['shared_module_count']:,}** modules",
        f"- Geometric-only: **{route['geometric_unique_module_count']:,}** modules",
        f"- Analytic-only: **{route['analytic_unique_module_count']:,}** modules",
        f"- Jaccard overlap: **{route['jaccard_module_overlap']:.6f}**",
        (
            "- Geometric closure imports analytic final root: "
            f"**{route['geometric_imports_analytic_root']}**"
        ),
        (
            "- Analytic closure imports geometric final root: "
            f"**{route['analytic_imports_geometric_root']}**"
        ),
        "",
        "Static non-import of the other final wrapper is necessary but not",
        "sufficient for independence; shared mathematical providers and causal",
        "development history remain separate review obligations.",
        "",
        "## High-confidence policy boundary",
        "",
    ]

    severe: list[dict[str, Any]] = []
    for target in report["targets"].values():
        severe.extend(
            finding
            for finding in target["findings"]
            if finding["severity"] == "critical"
        )

    if severe:
        for item in severe:
            lines.append(
                f"- **CRITICAL** `{item['category']}` — "
                f"`{item['path']}:{item['line']}` — `{item['symbol']}`"
            )
    else:
        lines.append(
            "- No critical static policy violation was found in the selected "
            "solution closures."
        )

    lines += [
        "",
        "## Required next evidence",
        "",
        "- Elaborate and print the exact target theorem types.",
        "- Run `#print axioms` on each selected declaration.",
        "- Replay the declared Comparator configurations in a clean environment.",
        "- Bind the effective patched dependency trees to each receipt.",
        "- Attempt an independent export/kernel check.",
        "- Compare the formal statements with the exact manuscript theorem.",
        "- Perform hostile mathematical review of every route-specific provider.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    os.chdir(ROOT)
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)

    head = run_git("rev-parse", "HEAD")
    head_tree = run_git("rev-parse", "HEAD^{tree}")
    base_tree = run_git("rev-parse", f"{BASE_REV}^{{tree}}")
    subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", BASE_REV, head],
        check=True,
    )

    target_receipts = {
        spec.key: build_target_receipt(spec)
        for spec in TARGETS
    }
    route_comparison = compare_routes(target_receipts)

    report = {
        "schema_version": "TheoremClosureStaticReceipt/1",
        "audit_identity": {
            "base_revision": BASE_REV,
            "base_tree": base_tree,
            "head_commit": head,
            "head_tree": head_tree,
            "scanner_path": str(Path(__file__).relative_to(ROOT)),
            "scanner_sha256": sha256_bytes(Path(__file__).read_bytes()),
        },
        "targets": target_receipts,
        "route_comparison": route_comparison,
        "policy": {
            "critical_categories": [
                "axiom_declaration",
                "sorry_token",
                "admit_token",
                "sorryAx_reference",
                "implemented_by",
                "extern_declaration",
                "challenge_imported_by_solution",
                "missing_internal_import",
                "invalid_utf8",
                "target_declaration_not_located",
            ],
            "ordinary_opaque_is_not_automatically_a_violation": True,
            "challenge_placeholders_are_not_solution_evidence": True,
        },
        "limits": [
            "Static source and import-closure scan only.",
            "Does not elaborate Lean or inspect generated environment objects.",
            "Does not establish theorem correctness, statement fidelity, "
            "originality, priority, authorship, or proof-route independence.",
            "External package modules are named but not traversed here.",
        ],
    }

    json_path = RESULT_ROOT / "theorem-closure-receipt.json"
    markdown_path = RESULT_ROOT / "theorem-closure-receipt.md"
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")

    critical_count = sum(
        target["critical_policy_violation_count"]
        for target in target_receipts.values()
    )
    receipt = {
        "schema_version": "TheoremClosureArtifactReceipt/1",
        "report_json": str(json_path.relative_to(ROOT)),
        "report_json_sha256": sha256_bytes(json_path.read_bytes()),
        "report_markdown": str(markdown_path.relative_to(ROOT)),
        "report_markdown_sha256": sha256_bytes(markdown_path.read_bytes()),
        "critical_policy_violation_count": critical_count,
    }
    receipt_path = RESULT_ROOT / "receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "targets": {
                    key: {
                        "modules": target["module_count"],
                        "critical_policy_violations": (
                            target["critical_policy_violation_count"]
                        ),
                        "external_import_roots": len(
                            target["external_imports"]
                        ),
                    }
                    for key, target in target_receipts.items()
                },
                "route_overlap": {
                    "shared_modules": route_comparison[
                        "shared_module_count"
                    ],
                    "jaccard": route_comparison[
                        "jaccard_module_overlap"
                    ],
                },
                **receipt,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if critical_count else 0


if __name__ == "__main__":
    sys.exit(main())
