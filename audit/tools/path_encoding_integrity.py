#!/usr/bin/env python3
"""Cross-platform Git path and text-encoding integrity scan.

This scanner protects source identity across Linux, macOS, Windows, archives,
Git clients, citation receipts, and migration tools. It does not judge the
mathematics or treat ordinary mathematical Unicode as suspicious.
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
BASE_REV = "fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb"
REPORT_DIR = ROOT / "audit" / "reports" / f"openai-math-{BASE_REV[:12]}"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

BIDI_CONTROLS = {
    "\u061c", "\u200e", "\u200f", "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
    "\u2066", "\u2067", "\u2068", "\u2069",
}
ZERO_WIDTH_CONTROLS = {"\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"}
WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
WINDOWS_INVALID = set('<>:"\\|?*')
TEXT_SUFFIXES = {
    ".lean", ".md", ".tex", ".bib", ".json", ".yaml", ".yml", ".toml", ".txt",
    ".py", ".sh", ".c", ".h", ".cpp", ".hpp", ".js", ".ts", ".css", ".html",
    ".xml", ".csv", ".gitignore", ".gitattributes", ".lake", ".patch", ".diff",
}
TEXT_BASENAMES = {"README", "LICENSE", "NOTICE", "COPYING", "lean-toolchain", "lakefile.lean"}
GENERATED_COMPONENTS = {".lake", "build", "dist", "target", "node_modules", "__pycache__", ".pytest_cache"}
GENERATED_SUFFIXES = {".olean", ".ilean", ".cmi", ".cmx", ".class", ".pyc", ".o", ".a", ".so", ".dylib", ".dll"}


def run_git(*args: str, binary: bool = False):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=not binary)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    path: str
    detail: str
    line: int | None = None
    codepoints: tuple[str, ...] = ()


def codepoints(chars: Iterable[str]) -> tuple[str, ...]:
    return tuple(f"U+{ord(ch):04X} {unicodedata.name(ch, 'UNNAMED')}" for ch in chars)


def index_records() -> list[tuple[str, str, str]]:
    raw = run_git("ls-files", "-s", "-z", binary=True)
    records: list[tuple[str, str, str]] = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        meta, path_raw = item.split(b"\t", 1)
        mode, oid, _stage = meta.decode("ascii").split()
        path = path_raw.decode("utf-8", "surrogateescape")
        records.append((mode, oid, path))
    return records


def display_path(path: str) -> str:
    return path.encode("utf-8", "backslashreplace").decode("utf-8")


def is_text_candidate(path: Path, size: int) -> bool:
    if size > 8 * 1024 * 1024:
        return False
    name = path.name
    suffix = path.suffix.lower()
    return suffix in TEXT_SUFFIXES or name in TEXT_BASENAMES or name.startswith("README") or name.startswith("LICENSE")


def component_portability(path: str) -> list[Finding]:
    result: list[Finding] = []
    shown = display_path(path)
    parts = PurePosixPath(path).parts
    for part in parts:
        if part != part.strip():
            result.append(Finding("high", "PATH_EDGE_WHITESPACE", shown, f"Component has leading/trailing whitespace: {part!r}"))
        if part.endswith("."):
            result.append(Finding("high", "PATH_TRAILING_DOT", shown, f"Component ends with a dot: {part!r}"))
        base = part.rstrip(" .").split(".", 1)[0].casefold()
        if base in WINDOWS_RESERVED:
            result.append(Finding("high", "WINDOWS_RESERVED_NAME", shown, f"Reserved Windows component: {part!r}"))
        bad = sorted(set(part) & WINDOWS_INVALID)
        if bad:
            result.append(Finding("medium", "WINDOWS_INVALID_CHARACTER", shown, f"Component contains Windows-invalid characters: {bad}"))
        if len(part.encode("utf-8", "surrogateescape")) > 255:
            result.append(Finding("high", "PATH_COMPONENT_TOO_LONG", shown, f"Component exceeds 255 UTF-8 bytes: {len(part.encode('utf-8', 'surrogateescape'))}"))
    if len(path.encode("utf-8", "surrogateescape")) > 240:
        result.append(Finding("medium", "PORTABLE_PATH_TOO_LONG", shown, f"Path is {len(path.encode('utf-8', 'surrogateescape'))} UTF-8 bytes"))
    return result


def control_findings(text: str, path: str, *, content: bool) -> list[Finding]:
    found: list[Finding] = []
    lines = text.splitlines() or [text]
    for number, line in enumerate(lines, 1):
        bidi = [ch for ch in line if ch in BIDI_CONTROLS]
        zero = [ch for ch in line if ch in ZERO_WIDTH_CONTROLS]
        controls = [ch for ch in line if unicodedata.category(ch) == "Cc" and ch not in "\t\n\r"]
        prefix = "CONTENT" if content else "PATH"
        if bidi:
            found.append(Finding("critical", f"{prefix}_BIDI_CONTROL", display_path(path), "Bidirectional override/isolate control present", number if content else None, codepoints(bidi)))
        if zero:
            found.append(Finding("high", f"{prefix}_ZERO_WIDTH_CONTROL", display_path(path), "Zero-width/format control present", number if content else None, codepoints(zero)))
        if controls:
            found.append(Finding("critical", f"{prefix}_CONTROL_CHARACTER", display_path(path), "Unexpected control character present", number if content else None, codepoints(controls)))
    return found


def safe_symlink(path: Path, rel: str) -> list[Finding]:
    findings: list[Finding] = []
    try:
        target = os.readlink(path)
    except OSError as exc:
        return [Finding("critical", "BROKEN_SYMLINK_INDEX", rel, f"Git mode is symlink but target cannot be read: {exc}")]
    target_path = PurePosixPath(target)
    if target_path.is_absolute():
        findings.append(Finding("critical", "ABSOLUTE_SYMLINK", rel, f"Absolute symlink target: {target}"))
    resolved = (path.parent / target).resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        findings.append(Finding("critical", "ESCAPING_SYMLINK", rel, f"Symlink escapes repository: {target}"))
    if not (path.parent / target).exists():
        findings.append(Finding("high", "DANGLING_SYMLINK", rel, f"Symlink target does not exist in checkout: {target}"))
    return findings


def scan() -> dict:
    records = index_records()
    findings: list[Finding] = []
    modes = collections.Counter()
    blob_paths: dict[str, list[str]] = collections.defaultdict(list)
    case_keys: dict[str, list[str]] = collections.defaultdict(list)
    nfc_keys: dict[str, list[str]] = collections.defaultdict(list)
    portable_keys: dict[str, list[str]] = collections.defaultdict(list)
    large_files: list[dict] = []
    lfs_pointers: list[dict] = []
    non_ascii_paths: list[str] = []
    line_endings = collections.Counter()
    text_scanned = 0
    text_bytes = 0
    generated_paths: list[str] = []
    executable_files: list[dict] = []

    for mode, oid, rel in records:
        shown = display_path(rel)
        modes[mode] += 1
        blob_paths[oid].append(shown)
        case_keys[rel.casefold()].append(shown)
        nfc_keys[unicodedata.normalize("NFC", rel)].append(shown)
        portable_keys[unicodedata.normalize("NFC", rel).casefold().rstrip(" .")].append(shown)
        if any(ord(ch) > 127 for ch in rel):
            non_ascii_paths.append(shown)
        if unicodedata.normalize("NFC", rel) != rel:
            findings.append(Finding("medium", "PATH_NOT_NFC", shown, "Path is not Unicode NFC-normalized"))
        findings.extend(control_findings(rel, rel, content=False))
        findings.extend(component_portability(rel))

        path = ROOT / rel
        if mode == "120000":
            findings.extend(safe_symlink(path, shown))
            continue
        if mode == "160000":
            findings.append(Finding("high", "GITLINK_SUBMODULE", shown, "Git submodule/gitlink is present and requires an independently pinned source receipt"))
            continue
        if not path.exists() or not path.is_file():
            findings.append(Finding("critical", "INDEX_WORKTREE_MISMATCH", shown, "Tracked regular file is absent from checkout"))
            continue

        size = path.stat().st_size
        if size >= 100 * 1024 * 1024:
            findings.append(Finding("high", "BLOB_OVER_100_MIB", shown, f"Tracked file is {size:,} bytes"))
        if size >= 10 * 1024 * 1024:
            large_files.append({"path": shown, "bytes": size, "oid": oid})
        if any(part in GENERATED_COMPONENTS for part in PurePosixPath(rel).parts) or path.suffix.lower() in GENERATED_SUFFIXES:
            generated_paths.append(shown)
        if mode == "100755":
            head = path.read_bytes()[:128]
            executable_files.append({"path": shown, "bytes": size, "has_shebang": head.startswith(b"#!")})
            if not head.startswith(b"#!"):
                findings.append(Finding("medium", "EXECUTABLE_WITHOUT_SHEBANG", shown, "Executable regular file lacks a shebang"))

        if size <= 2048:
            head = path.read_bytes()
            if head.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
                oid_match = re.search(rb"^oid sha256:([0-9a-f]{64})$", head, re.M)
                size_match = re.search(rb"^size (\d+)$", head, re.M)
                lfs_pointers.append({"path": shown, "oid": oid_match.group(1).decode() if oid_match else None, "size": int(size_match.group(1)) if size_match else None})

        if not is_text_candidate(path, size):
            continue
        data = path.read_bytes()
        text_scanned += 1
        text_bytes += len(data)
        if b"\x00" in data:
            findings.append(Finding("high", "NUL_IN_TEXT_FILE", shown, "Text-classified file contains NUL bytes"))
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            findings.append(Finding("critical", "INVALID_UTF8_TEXT", shown, f"UTF-8 decoding failed: {exc}"))
            continue
        if data.startswith(b"\xef\xbb\xbf"):
            findings.append(Finding("medium", "UTF8_BOM", shown, "UTF-8 BOM present"))
        crlf = data.count(b"\r\n")
        bare_lf = data.count(b"\n") - crlf
        bare_cr = data.count(b"\r") - crlf
        if crlf and bare_lf:
            line_endings["mixed_lf_crlf"] += 1
            findings.append(Finding("medium", "MIXED_LINE_ENDINGS", shown, f"Contains {crlf} CRLF and {bare_lf} LF line endings"))
        elif crlf:
            line_endings["crlf"] += 1
        else:
            line_endings["lf_or_single_line"] += 1
        if bare_cr:
            findings.append(Finding("high", "BARE_CR", shown, f"Contains {bare_cr} bare carriage returns"))
        if data and not data.endswith(b"\n"):
            findings.append(Finding("low", "NO_FINAL_NEWLINE", shown, "Text file lacks terminal newline"))
        findings.extend(control_findings(text, rel, content=True))

    for key, paths in case_keys.items():
        if len(set(paths)) > 1:
            findings.append(Finding("critical", "CASEFOLD_PATH_COLLISION", paths[0], f"Case-insensitive collision: {sorted(paths)}"))
    for key, paths in nfc_keys.items():
        if len(set(paths)) > 1:
            findings.append(Finding("critical", "NFC_PATH_COLLISION", paths[0], f"Unicode-normalization collision: {sorted(paths)}"))
    for key, paths in portable_keys.items():
        if len(set(paths)) > 1:
            findings.append(Finding("critical", "PORTABLE_PATH_COLLISION", paths[0], f"Portable normalized/casefolded collision: {sorted(paths)}"))

    duplicate_blobs = [
        {"oid": oid, "paths": sorted(paths), "count": len(paths)}
        for oid, paths in blob_paths.items() if len(paths) > 1
    ]
    duplicate_blobs.sort(key=lambda item: (-item["count"], item["oid"]))

    severity = collections.Counter(f.severity for f in findings)
    codes = collections.Counter(f.code for f in findings)
    return {
        "schema": "PathEncodingIntegrity/1",
        "source": {
            "base_revision": BASE_REV,
            "head_revision": run_git("rev-parse", "HEAD").strip(),
            "head_tree": run_git("rev-parse", "HEAD^{tree}").strip(),
            "scanner_sha256": sha256(Path(__file__).read_bytes()),
            "python": sys.version,
        },
        "counts": {
            "tracked_entries": len(records),
            "modes": dict(sorted(modes.items())),
            "text_files_scanned": text_scanned,
            "text_bytes_scanned": text_bytes,
            "non_ascii_paths": len(non_ascii_paths),
            "lfs_pointers": len(lfs_pointers),
            "large_files_over_10_mib": len(large_files),
            "generated_paths": len(generated_paths),
            "executable_files": len(executable_files),
            "duplicate_blob_groups": len(duplicate_blobs),
            "findings_by_severity": dict(sorted(severity.items())),
            "findings_by_code": dict(sorted(codes.items())),
            "line_endings": dict(sorted(line_endings.items())),
        },
        "findings": [asdict(f) for f in sorted(findings, key=lambda f: (f.severity, f.code, f.path, f.line or 0))],
        "non_ascii_paths": sorted(non_ascii_paths),
        "large_files": sorted(large_files, key=lambda item: (-item["bytes"], item["path"])),
        "lfs_pointers": sorted(lfs_pointers, key=lambda item: item["path"]),
        "generated_paths": sorted(generated_paths),
        "executable_files": sorted(executable_files, key=lambda item: item["path"]),
        "duplicate_blobs": duplicate_blobs,
        "limitations": [
            "Unicode confusability is not inferred from ordinary mathematical symbols.",
            "The scan is repository-structural and does not elaborate Lean or judge theorem correctness.",
            "Large and binary files are inventoried but not semantically parsed.",
        ],
    }


def render(report: dict) -> str:
    c = report["counts"]
    lines = [
        "# Path and encoding integrity report", "",
        f"- Base revision: `{report['source']['base_revision']}`",
        f"- Audit head: `{report['source']['head_revision']}`",
        f"- Audit tree: `{report['source']['head_tree']}`",
        f"- Scanner SHA-256: `{report['source']['scanner_sha256']}`", "",
        "## Counts", "",
        f"- Tracked entries: **{c['tracked_entries']:,}**",
        f"- Text files scanned: **{c['text_files_scanned']:,}** ({c['text_bytes_scanned']:,} bytes)",
        f"- Non-ASCII paths: **{c['non_ascii_paths']:,}**",
        f"- Large files over 10 MiB: **{c['large_files_over_10_mib']:,}**",
        f"- LFS pointers: **{c['lfs_pointers']:,}**",
        f"- Generated/build-like tracked paths: **{c['generated_paths']:,}**",
        f"- Duplicate blob groups: **{c['duplicate_blob_groups']:,}**", "",
        "## Findings", "",
        "| Severity | Code | Count |", "|---|---|---:|",
    ]
    severity_by_code = collections.Counter((f["severity"], f["code"]) for f in report["findings"])
    for (severity, code), count in sorted(severity_by_code.items()):
        lines.append(f"| {severity} | `{code}` | {count} |")
    critical = [f for f in report["findings"] if f["severity"] in {"critical", "high"}]
    lines += ["", "## Critical and high findings", ""]
    if not critical:
        lines.append("No critical or high path/encoding findings were detected.")
    for f in critical[:300]:
        where = f"`{f['path']}`" + (f":{f['line']}" if f.get("line") else "")
        lines.append(f"- **{f['severity'].upper()}** `{f['code']}` — {where}: {f['detail']}")
    if len(critical) > 300:
        lines.append(f"- … {len(critical)-300:,} additional findings are retained in JSON.")
    lines += ["", "## Boundary", "", "This report protects path and byte identity across environments. It does not establish mathematical correctness, originality, authorship, or proof completeness.", ""]
    return "\n".join(lines)


def main() -> int:
    subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", BASE_REV, "HEAD"], check=True)
    report = scan()
    jp = REPORT_DIR / "path-encoding-integrity.json"
    mp = REPORT_DIR / "path-encoding-integrity.md"
    jp.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    mp.write_text(render(report), encoding="utf-8")
    receipt = {
        "json": str(jp.relative_to(ROOT)), "json_sha256": sha256(jp.read_bytes()),
        "markdown": str(mp.relative_to(ROOT)), "markdown_sha256": sha256(mp.read_bytes()),
    }
    (REPORT_DIR / "path-encoding-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"counts": report["counts"], **receipt}, indent=2, sort_keys=True))
    blocking = sum(1 for f in report["findings"] if f["severity"] == "critical")
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
