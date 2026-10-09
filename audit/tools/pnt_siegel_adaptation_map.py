#!/usr/bin/env python3
"""Map the locally patched PrimeNumberTheoremAnd Siegel-zero subtree to nominal upstream source.

This scanner runs after ``lake update``.  It treats the package checkout's Git
HEAD as the nominal upstream identity and its working tree as the effective,
post-patch source.  It does not infer authorship, originality, or semantic
equivalence from textual similarity.
"""

from __future__ import annotations

import difflib
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

ROOT = Path(__file__).resolve().parents[2]
LEAN_ROOT = ROOT / "lean"
PACKAGE_ROOT = LEAN_ROOT / ".lake" / "packages" / "PrimeNumberTheoremAnd"
ADAPTED_ROOT = PACKAGE_ROOT / "PrimeNumberTheoremAnd" / "SiegelZeros"
PATCH_PATH = LEAN_ROOT / "patches" / "PrimeNumberTheoremAnd-lean4341.patch"
RESULT_ROOT = ROOT / "audit" / "results" / "pnt-siegel-adaptation"

EXPECTED_HEAD = "c39a751132c88b6e8080b74c74023fd95b3d8be0"
EXPECTED_PATCH_SHA256 = "b337d7bdfb75a4c93c34f6ad456834949b6627ade75b99e60336157acfa93603"
# The SHA above is checked against raw bytes.  If the frozen patch changes,
# this scanner must be reviewed and deliberately updated.

ADAPTED_PREFIX = "PrimeNumberTheoremAnd/SiegelZeros/"
CORE_DECLARATION = "hadamard_factorization_of_growth"

TRUST_TOKENS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("critical", "sorry", re.compile(r"\bsorry\b")),
    ("critical", "admit", re.compile(r"\badmit\b")),
    ("critical", "sorryAx", re.compile(r"\bsorryAx\b")),
    ("critical", "axiom", re.compile(r"(?m)^\s*(?:(?:private|protected)\s+)*axiom\b")),
    ("high", "unsafe", re.compile(r"\bunsafe\b")),
    ("review", "opaque", re.compile(r"(?m)^\s*(?:(?:private|protected|noncomputable)\s+)*opaque\b")),
)

DECL_RE = re.compile(
    r"(?m)^\s*(?:(?:@\[[^\n]*\]\s*)*)"
    r"(?:(?:private|protected|noncomputable|local|public)\s+)*"
    r"(theorem|lemma|def|abbrev|opaque|axiom|instance|structure|class)\s+"
    r"([^\s:({]+)"
)

CANONICAL_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("divisorZeroIndex₀Val_ne_zero", "divisorZeroIndex₀_val_ne_zero"),
    ("divisorZeroIndex₀Val", "divisorZeroIndex₀_val"),
    ("SiegelZeros.Complex.Hadamard.", "Complex.Hadamard."),
    ("_root_.SiegelZeros.Complex.", "Complex."),
    ("_root_.SiegelZeros.Real.", "Real."),
)


@dataclass(frozen=True)
class Declaration:
    kind: str
    short_name: str
    path: str
    line: int
    source_sha256: str
    region_sha256: str
    statement_sha256: str
    canonical_statement_sha256: str
    normalized_statement: str
    canonical_statement: str


@dataclass(frozen=True)
class Finding:
    severity: str
    category: str
    path: str
    line: int
    detail: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def run_git(*args: str, cwd: Path = PACKAGE_ROOT, check: bool = True) -> bytes:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({proc.returncode}):\n"
            f"{proc.stderr.decode('utf-8', 'replace')}"
        )
    return proc.stdout


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PACKAGE_ROOT))
    except ValueError:
        return str(path)


def strip_lean_comments_and_strings(text: str) -> str:
    """Blank Lean comments and strings while preserving offsets and newlines."""
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


def normalize_statement(text: str) -> str:
    text = re.sub(r"@\[[^\]]*\]\s*", "", text)
    text = re.sub(
        r"\b(?:private|protected|noncomputable|local|public)\s+", "", text
    )
    return " ".join(text.split())


def canonicalize_statement(text: str) -> str:
    result = normalize_statement(text)
    for old, new in CANONICAL_REPLACEMENTS:
        result = result.replace(old, new)
    return result


def statement_end(stripped: str, start: int, region_end: int) -> int:
    """Find the first source-level declaration body marker."""
    candidates: list[int] = []
    assign = stripped.find(":=", start, region_end)
    if assign >= 0:
        candidates.append(assign)
    # Structure/class declarations can use ``where`` without ``:=``.
    where_match = re.search(r"\bwhere\b", stripped[start:region_end])
    if where_match:
        candidates.append(start + where_match.start())
    return min(candidates) if candidates else region_end


def parse_declarations(path: Path) -> list[Declaration]:
    raw_bytes = path.read_bytes()
    raw = raw_bytes.decode("utf-8")
    stripped = strip_lean_comments_and_strings(raw)
    matches = list(DECL_RE.finditer(stripped))
    result: list[Declaration] = []
    source_sha = sha256_bytes(raw_bytes)
    for index, match in enumerate(matches):
        start = match.start()
        region_end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        end = statement_end(stripped, start, region_end)
        statement_raw = raw[start:end]
        region_raw = raw[start:region_end]
        normalized = normalize_statement(statement_raw)
        canonical = canonicalize_statement(statement_raw)
        result.append(
            Declaration(
                kind=match.group(1),
                short_name=match.group(2).rsplit(".", 1)[-1],
                path=display_path(path),
                line=raw.count("\n", 0, start) + 1,
                source_sha256=source_sha,
                region_sha256=sha256_bytes(region_raw.encode("utf-8")),
                statement_sha256=sha256_bytes(normalized.encode("utf-8")),
                canonical_statement_sha256=sha256_bytes(canonical.encode("utf-8")),
                normalized_statement=normalized,
                canonical_statement=canonical,
            )
        )
    return result


def normalized_file_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    stripped = strip_lean_comments_and_strings(raw)
    stripped = re.sub(r"(?m)^\s*module\s*$", "", stripped)
    stripped = re.sub(r"(?m)^\s*@\[expose\]\s+public\s+section\s*$", "", stripped)
    stripped = re.sub(r"(?m)^\s*public\s+import\s+", "import ", stripped)
    stripped = re.sub(r"(?m)^\s*public\s+", "", stripped)
    for old, new in CANONICAL_REPLACEMENTS:
        stripped = stripped.replace(old, new)
    return " ".join(stripped.split())


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def parse_patch_new_files(patch_text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    chunks = re.split(r"(?m)(?=^diff --git a/)", patch_text)
    for chunk in chunks:
        header = re.match(r"diff --git a/(.+?) b/(.+?)\n", chunk)
        if not header:
            continue
        old_path, new_path = header.groups()
        if not new_path.startswith(ADAPTED_PREFIX):
            continue
        if "\nnew file mode " not in chunk:
            continue
        added = 0
        for hunk in re.finditer(r"(?m)^@@ -\d+(?:,\d+)? \+\d+(?:,(\d+))? @@", chunk):
            added += int(hunk.group(1) or "1")
        records.append(
            {
                "old_path": old_path,
                "new_path": new_path,
                "added_lines_from_hunks": added,
                "patch_chunk_sha256": sha256_bytes(chunk.encode("utf-8")),
            }
        )
    return sorted(records, key=lambda x: x["new_path"])


def copyright_notices(text: str) -> dict[str, list[str]]:
    copyrights = sorted(set(re.findall(r"Copyright[^\n]+", text)))
    authors: set[str] = set()
    for payload in re.findall(r"Authors?:\s*([^\n]+)", text):
        authors.update(item.strip() for item in payload.split(",") if item.strip())
    return {"copyright_lines": copyrights, "named_authors": sorted(authors)}


def git_blob(path: Path) -> str:
    return run_git("hash-object", str(path)).decode("ascii").strip()


def git_status(path: Path) -> list[str]:
    raw = run_git(
        "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", str(path)
    )
    return [
        item.decode("utf-8", "surrogateescape")
        for item in raw.split(b"\0")
        if item
    ]


def find_same_basename_candidates(adapted: Path, all_nominal: Iterable[Path]) -> list[Path]:
    return sorted(
        (path for path in all_nominal if path.name == adapted.name),
        key=lambda p: display_path(p),
    )


def scan_trust(path: Path) -> list[Finding]:
    raw = path.read_text(encoding="utf-8")
    stripped = strip_lean_comments_and_strings(raw)
    findings: list[Finding] = []
    for severity, category, pattern in TRUST_TOKENS:
        for match in pattern.finditer(stripped):
            line = stripped.count("\n", 0, match.start()) + 1
            findings.append(
                Finding(
                    severity=severity,
                    category=category,
                    path=display_path(path),
                    line=line,
                    detail=match.group(0),
                )
            )
    return findings


def declaration_match(
    declaration: Declaration,
    candidates: list[Declaration],
) -> dict[str, Any]:
    ranked: list[dict[str, Any]] = []
    for candidate in candidates:
        ratio = similarity(declaration.canonical_statement, candidate.canonical_statement)
        if (
            declaration.canonical_statement_sha256
            == candidate.canonical_statement_sha256
        ):
            classification = "EXACT_CANONICAL_STATEMENT"
        elif ratio >= 0.98:
            classification = "VERY_HIGH_STATEMENT_SIMILARITY"
        elif ratio >= 0.90:
            classification = "HIGH_STATEMENT_SIMILARITY"
        else:
            classification = "NAME_MATCH_STATEMENT_DIFF"
        ranked.append(
            {
                "path": candidate.path,
                "line": candidate.line,
                "kind": candidate.kind,
                "statement_sha256": candidate.statement_sha256,
                "canonical_statement_sha256": candidate.canonical_statement_sha256,
                "canonical_similarity": round(ratio, 9),
                "classification": classification,
            }
        )
    ranked.sort(
        key=lambda item: (
            -item["canonical_similarity"], item["path"], item["line"]
        )
    )
    best = ranked[0] if ranked else None
    return {
        "adapted": asdict(declaration),
        "same_short_name_candidate_count": len(ranked),
        "best_candidate": best,
        "top_candidates": ranked[:5],
        "classification": best["classification"] if best else "NO_NAME_MATCH",
    }


def main() -> int:
    os.chdir(ROOT)
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)

    problems: list[str] = []
    if not PACKAGE_ROOT.exists():
        print(f"missing package checkout: {PACKAGE_ROOT}", file=sys.stderr)
        return 2
    if not ADAPTED_ROOT.exists():
        print(f"missing adapted subtree: {ADAPTED_ROOT}", file=sys.stderr)
        return 2

    head = run_git("rev-parse", "HEAD").decode("ascii").strip()
    if head != EXPECTED_HEAD:
        problems.append(f"unexpected package HEAD: {head}")

    patch_sha = sha256_file(PATCH_PATH)
    if patch_sha != EXPECTED_PATCH_SHA256:
        problems.append(
            f"patch SHA-256 mismatch: expected {EXPECTED_PATCH_SHA256}, observed {patch_sha}"
        )

    patch_text = PATCH_PATH.read_text(encoding="utf-8")
    patch_records = parse_patch_new_files(patch_text)
    patch_paths = {record["new_path"] for record in patch_records}

    adapted_lean_files = sorted(ADAPTED_ROOT.rglob("*.lean"))
    adapted_all_files = sorted(
        path for path in ADAPTED_ROOT.rglob("*") if path.is_file()
    )
    actual_paths = {display_path(path) for path in adapted_all_files}
    missing_patch_files = sorted(patch_paths - actual_paths)
    extra_actual_files = sorted(actual_paths - patch_paths)
    if missing_patch_files:
        problems.append(f"patch-added paths missing after update: {missing_patch_files}")

    nominal_lean_files = sorted(
        path
        for path in (PACKAGE_ROOT / "PrimeNumberTheoremAnd").rglob("*.lean")
        if ADAPTED_ROOT not in path.parents and path != ADAPTED_ROOT
    )

    nominal_declarations_by_name: defaultdict[str, list[Declaration]] = defaultdict(list)
    nominal_parse_errors: list[dict[str, str]] = []
    for path in nominal_lean_files:
        try:
            for declaration in parse_declarations(path):
                nominal_declarations_by_name[declaration.short_name].append(declaration)
        except (UnicodeDecodeError, OSError) as exc:
            nominal_parse_errors.append({"path": display_path(path), "error": str(exc)})

    file_records: list[dict[str, Any]] = []
    all_declaration_matches: list[dict[str, Any]] = []
    trust_findings: list[Finding] = []
    core_matches: list[dict[str, Any]] = []

    for path in adapted_lean_files:
        raw = path.read_text(encoding="utf-8")
        declarations = parse_declarations(path)
        trust_findings.extend(scan_trust(path))
        declaration_matches = []
        for declaration in declarations:
            match = declaration_match(
                declaration,
                nominal_declarations_by_name.get(declaration.short_name, []),
            )
            declaration_matches.append(match)
            all_declaration_matches.append(match)
            if declaration.short_name == CORE_DECLARATION:
                core_matches.append(match)

        same_basename = find_same_basename_candidates(path, nominal_lean_files)
        normalized_adapted = normalized_file_text(path)
        file_candidates = []
        for candidate in same_basename:
            candidate_text = normalized_file_text(candidate)
            file_candidates.append(
                {
                    "path": display_path(candidate),
                    "git_blob": git_blob(candidate),
                    "status": git_status(candidate),
                    "canonical_text_similarity": round(
                        similarity(normalized_adapted, candidate_text), 9
                    ),
                    "sha256": sha256_file(candidate),
                    "line_count": len(candidate.read_text(encoding="utf-8").splitlines()),
                    "notices": copyright_notices(
                        candidate.read_text(encoding="utf-8")
                    ),
                }
            )
        file_candidates.sort(
            key=lambda item: (-item["canonical_text_similarity"], item["path"])
        )

        file_records.append(
            {
                "path": display_path(path),
                "sha256": sha256_file(path),
                "git_blob": git_blob(path),
                "status": git_status(path),
                "bytes": path.stat().st_size,
                "line_count": len(raw.splitlines()),
                "notices_in_file": copyright_notices(raw),
                "declaration_count": len(declarations),
                "declaration_matches": declaration_matches,
                "same_basename_candidates": file_candidates,
            }
        )

    if not core_matches:
        problems.append(f"core declaration not found: {CORE_DECLARATION}")
    elif not any(
        match["best_candidate"]
        and match["best_candidate"]["canonical_similarity"] >= 0.90
        for match in core_matches
    ):
        problems.append("core declaration lacks a high-similarity nominal-source candidate")

    critical_trust = [finding for finding in trust_findings if finding.severity == "critical"]
    if critical_trust:
        problems.append(f"critical trust findings in adapted subtree: {len(critical_trust)}")

    notice_path = ADAPTED_ROOT / "NOTICE.md"
    notice = (
        {
            "path": display_path(notice_path),
            "sha256": sha256_file(notice_path),
            "text": notice_path.read_text(encoding="utf-8"),
            "notices": copyright_notices(notice_path.read_text(encoding="utf-8")),
        }
        if notice_path.exists()
        else None
    )
    if notice is None:
        problems.append("adapted subtree NOTICE.md is missing")

    exact = sum(
        1
        for item in all_declaration_matches
        if item["classification"] == "EXACT_CANONICAL_STATEMENT"
    )
    very_high = sum(
        1
        for item in all_declaration_matches
        if item["classification"] == "VERY_HIGH_STATEMENT_SIMILARITY"
    )
    high = sum(
        1
        for item in all_declaration_matches
        if item["classification"] == "HIGH_STATEMENT_SIMILARITY"
    )
    no_match = sum(
        1
        for item in all_declaration_matches
        if item["classification"] == "NO_NAME_MATCH"
    )

    package_lakefile_candidates = [
        path for path in (PACKAGE_ROOT / "lakefile.lean", PACKAGE_ROOT / "lakefile.toml") if path.exists()
    ]
    library_root_present = False
    package_lakefiles = []
    for path in package_lakefile_candidates:
        text = path.read_text(encoding="utf-8")
        present = "PrimeNumberTheoremAndSiegelZeros" in text
        library_root_present = library_root_present or present
        package_lakefiles.append(
            {
                "path": display_path(path),
                "sha256": sha256_file(path),
                "contains_adapted_library": present,
                "status": git_status(path),
            }
        )
    if not library_root_present:
        problems.append("adapted Lake library root was not found")

    report = {
        "schema_version": "AdaptedFormalSourceMap/1",
        "classification": [
            "ADAPTED_UPSTREAM_FORMAL_SOURCE",
            "SEMANTIC_EQUIVALENCE_UNREVIEWED",
            "PATCH_AUTHORSHIP_UNRESOLVED",
        ],
        "identity": {
            "nominal_repository": "https://github.com/AlexKontorovich/PrimeNumberTheoremAnd",
            "nominal_head": head,
            "expected_nominal_head": EXPECTED_HEAD,
            "effective_tree": run_git("write-tree").decode("ascii").strip(),
            "package_status_sha256": sha256_bytes(
                run_git("status", "--porcelain=v1", "-z", "--untracked-files=all")
            ),
            "patch_path": str(PATCH_PATH.relative_to(ROOT)),
            "patch_sha256": patch_sha,
            "expected_patch_sha256": EXPECTED_PATCH_SHA256,
            "scanner_path": str(Path(__file__).relative_to(ROOT)),
            "scanner_sha256": sha256_file(Path(__file__)),
        },
        "patch_added_files": patch_records,
        "patch_added_file_count": len(patch_records),
        "patch_added_lean_line_count": sum(
            record["added_lines_from_hunks"]
            for record in patch_records
            if record["new_path"].endswith(".lean")
        ),
        "actual_adapted_files": sorted(actual_paths),
        "missing_patch_files": missing_patch_files,
        "extra_actual_files": extra_actual_files,
        "notice": notice,
        "package_lakefiles": package_lakefiles,
        "files": file_records,
        "declaration_summary": {
            "adapted_declaration_count": len(all_declaration_matches),
            "exact_canonical_statement_count": exact,
            "very_high_similarity_count": very_high,
            "high_similarity_count": high,
            "no_name_match_count": no_match,
        },
        "core_declaration_matches": core_matches,
        "trust_findings": [asdict(item) for item in trust_findings],
        "nominal_parse_errors": nominal_parse_errors,
        "problems": problems,
        "limits": [
            "Textual declaration matching is not semantic equivalence.",
            "Short-name matches can be ambiguous and are retained as candidates.",
            "Known API renames are canonicalized only for comparison and raw hashes are retained.",
            "Patch authorship is not inferred from Git ownership or retained source notices.",
            "Only Lean source present in the fetched nominal package is considered as an origin candidate.",
        ],
    }

    json_path = RESULT_ROOT / "adapted-formal-source-map.json"
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    markdown_lines = [
        "# PrimeNumberTheoremAnd Siegel-zero adaptation map",
        "",
        f"- Nominal head: `{head}`",
        f"- Effective tree: `{report['identity']['effective_tree']}`",
        f"- Patch SHA-256: `{patch_sha}`",
        f"- Patch-added files: **{len(patch_records)}**",
        f"- Patch-added Lean lines: **{report['patch_added_lean_line_count']:,}**",
        f"- Adapted declarations: **{len(all_declaration_matches):,}**",
        f"- Exact canonical statement candidates: **{exact:,}**",
        f"- Very-high-similarity candidates: **{very_high:,}**",
        f"- High-similarity candidates: **{high:,}**",
        f"- No short-name candidate: **{no_match:,}**",
        "",
        "## Classification",
        "",
        "`ADAPTED_UPSTREAM_FORMAL_SOURCE` · `SEMANTIC_EQUIVALENCE_UNREVIEWED` · "
        "`PATCH_AUTHORSHIP_UNRESOLVED`",
        "",
        "## Added files",
        "",
        "| Path | Lines | Declarations | Best same-basename candidate | File similarity |",
        "|---|---:|---:|---|---:|",
    ]
    file_by_path = {item["path"]: item for item in file_records}
    for patch_record in patch_records:
        path = patch_record["new_path"]
        file_record = file_by_path.get(path)
        if file_record:
            candidates = file_record["same_basename_candidates"]
            best = candidates[0] if candidates else None
            markdown_lines.append(
                f"| `{path}` | {patch_record['added_lines_from_hunks']:,} | "
                f"{file_record['declaration_count']:,} | "
                f"`{best['path'] if best else 'none'}` | "
                f"{best['canonical_text_similarity'] if best else 0:.6f} |"
            )
        else:
            markdown_lines.append(
                f"| `{path}` | {patch_record['added_lines_from_hunks']:,} | — | — | — |"
            )

    markdown_lines += ["", "## Core declaration", ""]
    for match in core_matches:
        best = match["best_candidate"]
        markdown_lines.append(
            f"- `{match['adapted']['path']}:{match['adapted']['line']}` → "
            f"`{best['path']}:{best['line']}`; "
            f"classification `{match['classification']}`; "
            f"similarity `{best['canonical_similarity']:.9f}`."
            if best
            else f"- `{match['adapted']['path']}:{match['adapted']['line']}` has no candidate."
        )

    markdown_lines += ["", "## Policy result", ""]
    if problems:
        markdown_lines.extend(f"- **BLOCKING:** {problem}" for problem in problems)
    else:
        markdown_lines.append("- Structural adaptation-map gate passed.")
    markdown_lines += [
        "",
        "> Passing this structural gate does not establish semantic equivalence, authorship,",
        "> originality, or mathematical correctness.",
        "",
    ]
    md_path = RESULT_ROOT / "adapted-formal-source-map.md"
    md_path.write_text("\n".join(markdown_lines), encoding="utf-8")

    receipt = {
        "schema_version": "AdaptedFormalSourceMapArtifact/1",
        "report_json": str(json_path.relative_to(ROOT)),
        "report_json_sha256": sha256_file(json_path),
        "report_markdown": str(md_path.relative_to(ROOT)),
        "report_markdown_sha256": sha256_file(md_path),
        "problem_count": len(problems),
    }
    receipt_path = RESULT_ROOT / "receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "classification": report["classification"],
                "patch_added_file_count": len(patch_records),
                "patch_added_lean_line_count": report["patch_added_lean_line_count"],
                "declaration_summary": report["declaration_summary"],
                "problem_count": len(problems),
                **receipt,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
