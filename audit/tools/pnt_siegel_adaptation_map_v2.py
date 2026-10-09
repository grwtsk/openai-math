#!/usr/bin/env python3
"""Build an origin/similarity map for the patched PNT+ Siegel-zero subtree.

The nominal source identity is the pinned Git HEAD of the fetched
PrimeNumberTheoremAnd package.  The effective source identity is a temporary-
index Git tree that includes all tracked modifications and untracked,
non-ignored files created by the OpenAI patch.  The scanner never stages or
commits inside the actual package checkout.

Textual similarity is evidence for review routing only.  It is not semantic
equivalence, authorship, originality, or mathematical correctness.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
LEAN_ROOT = ROOT / "lean"
PACKAGE_ROOT = LEAN_ROOT / ".lake" / "packages" / "PrimeNumberTheoremAnd"
PACKAGE_SOURCE_ROOT = PACKAGE_ROOT / "PrimeNumberTheoremAnd"
ADAPTED_ROOT = PACKAGE_SOURCE_ROOT / "SiegelZeros"
PATCH_PATH = LEAN_ROOT / "patches" / "PrimeNumberTheoremAnd-lean4341.patch"
RESULT_ROOT = ROOT / "audit" / "results" / "pnt-siegel-adaptation"

EXPECTED_HEAD = "c39a751132c88b6e8080b74c74023fd95b3d8be0"
EXPECTED_PATCH_SHA256 = "0890432340c0025973bcfe070b634355fa366cc831595f68526e4c73c8903d82"
ADAPTED_PREFIX = "PrimeNumberTheoremAnd/SiegelZeros/"
CORE_DECLARATION = "hadamard_factorization_of_growth"

DECL_RE = re.compile(
    r"(?m)^\s*(?:(?:@\[[^\n]*\]\s*)*)"
    r"(?:(?:private|protected|noncomputable|local|public)\s+)*"
    r"(theorem|lemma|def|abbrev|opaque|axiom|instance|structure|class)\s+"
    r"([^\s:({]+)"
)

TRUST_TOKENS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("critical", "sorry", re.compile(r"\bsorry\b")),
    ("critical", "admit", re.compile(r"\badmit\b")),
    ("critical", "sorryAx", re.compile(r"\bsorryAx\b")),
    (
        "critical",
        "axiom",
        re.compile(r"(?m)^\s*(?:(?:private|protected)\s+)*axiom\b"),
    ),
    ("high", "unsafe", re.compile(r"\bunsafe\b")),
    (
        "review",
        "opaque",
        re.compile(
            r"(?m)^\s*(?:(?:private|protected|noncomputable)\s+)*opaque\b"
        ),
    ),
)

# Canonicalization is deliberately narrow and fully disclosed.  Raw bytes and
# uncanonicalized statement hashes remain in every record.
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


def run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    proc = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(args)}\n"
            f"stdout:\n{proc.stdout.decode('utf-8', 'replace')}\n"
            f"stderr:\n{proc.stderr.decode('utf-8', 'replace')}"
        )
    return proc


def git(*args: str, check: bool = True) -> bytes:
    return run(["git", *args], cwd=PACKAGE_ROOT, check=check).stdout


def display_path(path: Path) -> str:
    return str(path.relative_to(PACKAGE_ROOT))


def temporary_index_tree(repo: Path = PACKAGE_ROOT) -> str:
    """Write the effective source tree through an isolated temporary index."""
    with tempfile.TemporaryDirectory(prefix="pnt-effective-tree-") as td:
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(Path(td) / "index")
        run(["git", "read-tree", "HEAD"], cwd=repo, env=env)
        run(["git", "add", "-A", "--", "."], cwd=repo, env=env)
        return run(["git", "write-tree"], cwd=repo, env=env).stdout.decode(
            "ascii", "strict"
        ).strip()


def path_status(path: Path) -> list[str]:
    rel = display_path(path)
    raw = git(
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--",
        rel,
    )
    return [
        item.decode("utf-8", "surrogateescape")
        for item in raw.split(b"\0")
        if item
    ]


def git_blob(path: Path) -> str:
    return git("hash-object", display_path(path)).decode("ascii", "strict").strip()


def strip_lean_comments_and_strings(text: str) -> str:
    """Blank Lean comments and strings while preserving offsets/newlines."""
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
    result = re.sub(r"@\[[^\]]*\]\s*", "", text)
    result = re.sub(
        r"\b(?:private|protected|noncomputable|local|public)\s+", "", result
    )
    return " ".join(result.split())


def canonicalize_statement(text: str) -> str:
    result = normalize_statement(text)
    for old, new in CANONICAL_REPLACEMENTS:
        result = result.replace(old, new)
    return result


def declaration_body_offset(stripped: str, start: int, region_end: int) -> int:
    positions: list[int] = []
    assign = stripped.find(":=", start, region_end)
    if assign >= 0:
        positions.append(assign)
    where_match = re.search(r"\bwhere\b", stripped[start:region_end])
    if where_match:
        positions.append(start + where_match.start())
    return min(positions) if positions else region_end


def parse_declarations(path: Path) -> list[Declaration]:
    raw_bytes = path.read_bytes()
    raw = raw_bytes.decode("utf-8")
    stripped = strip_lean_comments_and_strings(raw)
    matches = list(DECL_RE.finditer(stripped))
    source_sha = sha256_bytes(raw_bytes)
    declarations: list[Declaration] = []
    for index, match in enumerate(matches):
        start = match.start()
        region_end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        body = declaration_body_offset(stripped, start, region_end)
        statement_raw = raw[start:body]
        region_raw = raw[start:region_end]
        normalized = normalize_statement(statement_raw)
        canonical = canonicalize_statement(statement_raw)
        declarations.append(
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
    return declarations


def normalized_file_text(path: Path) -> str:
    text = strip_lean_comments_and_strings(path.read_text(encoding="utf-8"))
    text = re.sub(r"(?m)^\s*module\s*$", "", text)
    text = re.sub(r"(?m)^\s*@\[expose\]\s+public\s+section\s*$", "", text)
    text = re.sub(r"(?m)^\s*public\s+import\s+", "import ", text)
    text = re.sub(r"(?m)^\s*public\s+", "", text)
    for old, new in CANONICAL_REPLACEMENTS:
        text = text.replace(old, new)
    return " ".join(text.split())


def similarity(left: str, right: str) -> float:
    return difflib.SequenceMatcher(None, left, right, autojunk=False).ratio()


def parse_patch_added_files(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for chunk in re.split(r"(?m)(?=^diff --git a/)", text):
        header = re.match(r"diff --git a/(.+?) b/(.+?)\n", chunk)
        if not header or "\nnew file mode " not in chunk:
            continue
        old_path, new_path = header.groups()
        if not new_path.startswith(ADAPTED_PREFIX):
            continue
        added = sum(
            int(match.group(1) or "1")
            for match in re.finditer(
                r"(?m)^@@ -\d+(?:,\d+)? \+\d+(?:,(\d+))? @@", chunk
            )
        )
        records.append(
            {
                "old_path": old_path,
                "new_path": new_path,
                "added_lines_from_hunks": added,
                "patch_chunk_sha256": sha256_bytes(chunk.encode("utf-8")),
            }
        )
    return sorted(records, key=lambda item: item["new_path"])


def notices(text: str) -> dict[str, list[str]]:
    copyright_lines = sorted(set(re.findall(r"Copyright[^\n]+", text)))
    authors: set[str] = set()
    for payload in re.findall(r"Authors?:\s*([^\n]+)", text):
        authors.update(item.strip() for item in payload.split(",") if item.strip())
    return {
        "copyright_lines": copyright_lines,
        "named_authors": sorted(authors),
    }


def trust_findings(path: Path) -> list[Finding]:
    stripped = strip_lean_comments_and_strings(path.read_text(encoding="utf-8"))
    result: list[Finding] = []
    for severity, category, pattern in TRUST_TOKENS:
        for match in pattern.finditer(stripped):
            result.append(
                Finding(
                    severity=severity,
                    category=category,
                    path=display_path(path),
                    line=stripped.count("\n", 0, match.start()) + 1,
                    detail=match.group(0),
                )
            )
    return result


def declaration_match(
    adapted: Declaration, candidates: Iterable[Declaration]
) -> dict[str, Any]:
    ranked: list[dict[str, Any]] = []
    for candidate in candidates:
        ratio = similarity(adapted.canonical_statement, candidate.canonical_statement)
        if adapted.canonical_statement_sha256 == candidate.canonical_statement_sha256:
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
    ranked.sort(key=lambda item: (-item["canonical_similarity"], item["path"], item["line"]))
    best = ranked[0] if ranked else None
    return {
        "adapted": asdict(adapted),
        "same_short_name_candidate_count": len(ranked),
        "best_candidate": best,
        "top_candidates": ranked[:5],
        "classification": best["classification"] if best else "NO_NAME_MATCH",
    }


def same_basename_candidates(
    adapted: Path, nominal_files: Iterable[Path]
) -> list[dict[str, Any]]:
    adapted_text = normalized_file_text(adapted)
    records: list[dict[str, Any]] = []
    for candidate in nominal_files:
        if candidate.name != adapted.name:
            continue
        raw = candidate.read_text(encoding="utf-8")
        records.append(
            {
                "path": display_path(candidate),
                "sha256": sha256_file(candidate),
                "git_blob": git_blob(candidate),
                "status": path_status(candidate),
                "line_count": len(raw.splitlines()),
                "notices": notices(raw),
                "canonical_text_similarity": round(
                    similarity(adapted_text, normalized_file_text(candidate)), 9
                ),
            }
        )
    records.sort(key=lambda item: (-item["canonical_text_similarity"], item["path"]))
    return records


def main() -> int:
    os.chdir(ROOT)
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []

    if not (PACKAGE_ROOT / ".git").exists():
        print(f"missing package checkout: {PACKAGE_ROOT}", file=sys.stderr)
        return 2
    if not ADAPTED_ROOT.exists():
        print(f"missing adapted subtree: {ADAPTED_ROOT}", file=sys.stderr)
        return 2

    nominal_head = git("rev-parse", "HEAD").decode("ascii", "strict").strip()
    if nominal_head != EXPECTED_HEAD:
        problems.append(f"unexpected package HEAD: {nominal_head}")

    patch_sha = sha256_file(PATCH_PATH)
    if patch_sha != EXPECTED_PATCH_SHA256:
        problems.append(
            f"patch SHA-256 mismatch: expected {EXPECTED_PATCH_SHA256}, observed {patch_sha}"
        )

    patch_records = parse_patch_added_files(PATCH_PATH.read_text(encoding="utf-8"))
    patch_paths = {item["new_path"] for item in patch_records}
    actual_files = sorted(path for path in ADAPTED_ROOT.rglob("*") if path.is_file())
    actual_paths = {display_path(path) for path in actual_files}
    missing_files = sorted(patch_paths - actual_paths)
    unexpected_files = sorted(actual_paths - patch_paths)
    if missing_files:
        problems.append(f"patch-added paths missing after update: {missing_files}")

    adapted_lean = sorted(ADAPTED_ROOT.rglob("*.lean"))
    nominal_lean = sorted(
        path
        for path in PACKAGE_SOURCE_ROOT.rglob("*.lean")
        if ADAPTED_ROOT not in path.parents
    )

    nominal_by_name: defaultdict[str, list[Declaration]] = defaultdict(list)
    nominal_parse_errors: list[dict[str, str]] = []
    for path in nominal_lean:
        try:
            for declaration in parse_declarations(path):
                nominal_by_name[declaration.short_name].append(declaration)
        except (OSError, UnicodeDecodeError) as exc:
            nominal_parse_errors.append({"path": display_path(path), "error": str(exc)})

    file_records: list[dict[str, Any]] = []
    declaration_matches: list[dict[str, Any]] = []
    findings: list[Finding] = []
    core_matches: list[dict[str, Any]] = []

    for path in adapted_lean:
        raw = path.read_text(encoding="utf-8")
        declarations = parse_declarations(path)
        findings.extend(trust_findings(path))
        matches = []
        for declaration in declarations:
            match = declaration_match(
                declaration, nominal_by_name.get(declaration.short_name, [])
            )
            matches.append(match)
            declaration_matches.append(match)
            if declaration.short_name == CORE_DECLARATION:
                core_matches.append(match)
        file_records.append(
            {
                "path": display_path(path),
                "sha256": sha256_file(path),
                "git_blob": git_blob(path),
                "status": path_status(path),
                "bytes": path.stat().st_size,
                "line_count": len(raw.splitlines()),
                "notices_in_file": notices(raw),
                "declaration_count": len(declarations),
                "declaration_matches": matches,
                "same_basename_candidates": same_basename_candidates(path, nominal_lean),
            }
        )

    critical_findings = [item for item in findings if item.severity == "critical"]
    if critical_findings:
        problems.append(
            f"critical trust findings in adapted subtree: {len(critical_findings)}"
        )

    if not core_matches:
        problems.append(f"core declaration not found: {CORE_DECLARATION}")
    elif not any(
        item["best_candidate"]
        and item["best_candidate"]["canonical_similarity"] >= 0.90
        for item in core_matches
    ):
        problems.append("core declaration lacks a high-similarity nominal-source candidate")

    notice_path = ADAPTED_ROOT / "NOTICE.md"
    notice_record = None
    if notice_path.exists():
        notice_text = notice_path.read_text(encoding="utf-8")
        notice_record = {
            "path": display_path(notice_path),
            "sha256": sha256_file(notice_path),
            "git_blob": git_blob(notice_path),
            "status": path_status(notice_path),
            "text": notice_text,
            "notices": notices(notice_text),
        }
    else:
        problems.append("adapted subtree NOTICE.md is missing")

    lakefile_records = []
    library_root_present = False
    for path in (PACKAGE_ROOT / "lakefile.lean", PACKAGE_ROOT / "lakefile.toml"):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        present = "PrimeNumberTheoremAndSiegelZeros" in text
        library_root_present = library_root_present or present
        lakefile_records.append(
            {
                "path": display_path(path),
                "sha256": sha256_file(path),
                "git_blob": git_blob(path),
                "status": path_status(path),
                "contains_adapted_library": present,
            }
        )
    if not library_root_present:
        problems.append("adapted Lake library root was not found")

    classifications = defaultdict(int)
    for item in declaration_matches:
        classifications[item["classification"]] += 1

    effective_tree = temporary_index_tree()
    package_status = git(
        "status", "--porcelain=v1", "-z", "--untracked-files=all"
    )

    report = {
        "schema_version": "AdaptedFormalSourceMap/2",
        "classification": [
            "ADAPTED_UPSTREAM_FORMAL_SOURCE",
            "SEMANTIC_EQUIVALENCE_UNREVIEWED",
            "PATCH_AUTHORSHIP_UNRESOLVED",
        ],
        "identity": {
            "nominal_repository": "https://github.com/AlexKontorovich/PrimeNumberTheoremAnd",
            "nominal_head": nominal_head,
            "expected_nominal_head": EXPECTED_HEAD,
            "nominal_head_tree": git("rev-parse", "HEAD^{tree}").decode("ascii", "strict").strip(),
            "effective_post_patch_tree": effective_tree,
            "package_status_sha256": sha256_bytes(package_status),
            "patch_path": str(PATCH_PATH.relative_to(ROOT)),
            "patch_sha256": patch_sha,
            "expected_patch_sha256": EXPECTED_PATCH_SHA256,
            "scanner_path": str(Path(__file__).relative_to(ROOT)),
            "scanner_sha256": sha256_file(Path(__file__)),
        },
        "patch_added_files": patch_records,
        "patch_added_file_count": len(patch_records),
        "patch_added_lean_line_count": sum(
            item["added_lines_from_hunks"]
            for item in patch_records
            if item["new_path"].endswith(".lean")
        ),
        "actual_adapted_files": sorted(actual_paths),
        "missing_patch_files": missing_files,
        "unexpected_adapted_files": unexpected_files,
        "notice": notice_record,
        "package_lakefiles": lakefile_records,
        "files": file_records,
        "declaration_summary": {
            "adapted_declaration_count": len(declaration_matches),
            "classifications": dict(sorted(classifications.items())),
        },
        "core_declaration_matches": core_matches,
        "trust_findings": [asdict(item) for item in findings],
        "nominal_parse_errors": nominal_parse_errors,
        "problems": problems,
        "limits": [
            "Textual declaration matching is not semantic equivalence.",
            "Short-name matches can be ambiguous and are retained as candidates.",
            "Known API renames are canonicalized only for comparison; raw hashes remain.",
            "Patch authorship is not inferred from repository ownership or source notices.",
            "Only source present in the pinned fetched package is considered as an origin candidate.",
        ],
    }

    json_path = RESULT_ROOT / "adapted-formal-source-map-v2.json"
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    file_by_path = {item["path"]: item for item in file_records}
    md = [
        "# PrimeNumberTheoremAnd Siegel-zero adaptation map",
        "",
        f"- Nominal head: `{nominal_head}`",
        f"- Nominal tree: `{report['identity']['nominal_head_tree']}`",
        f"- Effective post-patch tree: `{effective_tree}`",
        f"- Patch SHA-256: `{patch_sha}`",
        f"- Patch-added files: **{len(patch_records)}**",
        f"- Patch-added Lean lines: **{report['patch_added_lean_line_count']:,}**",
        f"- Adapted declarations: **{len(declaration_matches):,}**",
        "",
        "## Classification",
        "",
        "`ADAPTED_UPSTREAM_FORMAL_SOURCE` · `SEMANTIC_EQUIVALENCE_UNREVIEWED` · "
        "`PATCH_AUTHORSHIP_UNRESOLVED`",
        "",
        "## Declaration matching",
        "",
    ]
    for key, count in sorted(classifications.items()):
        md.append(f"- `{key}`: **{count:,}**")

    md += [
        "",
        "## Added files",
        "",
        "| Path | Added lines | Declarations | Best same-basename candidate | Similarity |",
        "|---|---:|---:|---|---:|",
    ]
    for patch_record in patch_records:
        path = patch_record["new_path"]
        file_record = file_by_path.get(path)
        if file_record is None:
            md.append(
                f"| `{path}` | {patch_record['added_lines_from_hunks']:,} | — | — | — |"
            )
            continue
        candidates = file_record["same_basename_candidates"]
        best = candidates[0] if candidates else None
        md.append(
            f"| `{path}` | {patch_record['added_lines_from_hunks']:,} | "
            f"{file_record['declaration_count']:,} | "
            f"`{best['path'] if best else 'none'}` | "
            f"{best['canonical_text_similarity'] if best else 0:.6f} |"
        )

    md += ["", "## Core declaration", ""]
    for item in core_matches:
        best = item["best_candidate"]
        if best:
            md.append(
                f"- `{item['adapted']['path']}:{item['adapted']['line']}` → "
                f"`{best['path']}:{best['line']}`; `{item['classification']}`; "
                f"similarity `{best['canonical_similarity']:.9f}`."
            )
        else:
            md.append(
                f"- `{item['adapted']['path']}:{item['adapted']['line']}` has no candidate."
            )

    md += ["", "## Policy result", ""]
    if problems:
        md.extend(f"- **BLOCKING:** {problem}" for problem in problems)
    else:
        md.append("- Structural adaptation-map gate passed.")
    md += [
        "",
        "> A passing structural gate does not establish semantic equivalence, authorship,",
        "> originality, or mathematical correctness.",
        "",
    ]
    md_path = RESULT_ROOT / "adapted-formal-source-map-v2.md"
    md_path.write_text("\n".join(md), encoding="utf-8")

    receipt = {
        "schema_version": "AdaptedFormalSourceMapArtifact/2",
        "report_json": str(json_path.relative_to(ROOT)),
        "report_json_sha256": sha256_file(json_path),
        "report_markdown": str(md_path.relative_to(ROOT)),
        "report_markdown_sha256": sha256_file(md_path),
        "problem_count": len(problems),
    }
    receipt_path = RESULT_ROOT / "receipt-v2.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "classification": report["classification"],
                "nominal_head": nominal_head,
                "effective_post_patch_tree": effective_tree,
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
