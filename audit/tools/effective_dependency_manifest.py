#!/usr/bin/env python3
"""Record effective post-patch dependency identities without mutating source.

For each Lake package checkout this writes the pinned commit, origin, current
working-tree status, binary diff digest, and a Git tree object produced through
a temporary index.  The temporary-index tree includes tracked modifications
and untracked non-ignored files while leaving the package's real index intact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LEAN_ROOT = ROOT / "lean"
PACKAGES_ROOT = LEAN_ROOT / ".lake" / "packages"
PATCH_ROOT = LEAN_ROOT / "patches"


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


def text(args: list[str], *, cwd: Path, check: bool = True) -> str:
    return run(args, cwd=cwd, check=check).stdout.decode("utf-8", "strict").strip()


def normalize_manifest_name(name: str) -> str:
    return name.removeprefix("«").removesuffix("»")


def temporary_index_tree(repo: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="effective-tree-") as td:
        index_path = Path(td) / "index"
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(index_path)
        run(["git", "read-tree", "HEAD"], cwd=repo, env=env)
        run(["git", "add", "-A", "--", "."], cwd=repo, env=env)
        proc = run(["git", "write-tree"], cwd=repo, env=env)
        return proc.stdout.decode("ascii", "strict").strip()


def package_record(
    directory: Path,
    expected: dict[str, Any] | None,
) -> dict[str, Any]:
    head = text(["git", "rev-parse", "HEAD"], cwd=directory)
    origin_proc = run(
        ["git", "remote", "get-url", "origin"], cwd=directory, check=False
    )
    origin = (
        origin_proc.stdout.decode("utf-8", "replace").strip()
        if origin_proc.returncode == 0
        else None
    )
    status = run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=directory,
    ).stdout
    diff = run(
        ["git", "diff", "--binary", "--no-ext-diff", "HEAD", "--", "."],
        cwd=directory,
    ).stdout
    effective_tree = temporary_index_tree(directory)

    status_entries = [
        item.decode("utf-8", "surrogateescape")
        for item in status.split(b"\0")
        if item
    ]
    expected_revision = expected.get("rev") if expected else None
    expected_url = expected.get("url") if expected else None

    return {
        "directory_name": directory.name,
        "path": str(directory.relative_to(ROOT)),
        "head_commit": head,
        "expected_revision": expected_revision,
        "head_matches_manifest": expected_revision == head if expected_revision else None,
        "origin": origin,
        "expected_url": expected_url,
        "origin_matches_manifest": origin == expected_url if expected_url else None,
        "status_entry_count": len(status_entries),
        "status_entries": status_entries,
        "status_sha256": sha256_bytes(status),
        "binary_diff_bytes": len(diff),
        "binary_diff_sha256": sha256_bytes(diff),
        "effective_git_tree": effective_tree,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output = (ROOT / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    manifest_path = LEAN_ROOT / "lake-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_packages = {
        normalize_manifest_name(item["name"]): item
        for item in manifest.get("packages", [])
        if item.get("type") == "git"
    }

    if not PACKAGES_ROOT.exists():
        raise RuntimeError(f"Lake packages directory is missing: {PACKAGES_ROOT}")

    records: list[dict[str, Any]] = []
    observed_names: set[str] = set()
    for directory in sorted(PACKAGES_ROOT.iterdir(), key=lambda p: p.name):
        if not directory.is_dir() or not (directory / ".git").exists():
            continue
        observed_names.add(directory.name)
        records.append(package_record(directory, expected_packages.get(directory.name)))

    missing_expected = sorted(set(expected_packages) - observed_names)
    unexpected_observed = sorted(observed_names - set(expected_packages))

    patches = []
    for path in sorted(PATCH_ROOT.glob("*.patch")):
        raw = path.read_bytes()
        patches.append(
            {
                "path": str(path.relative_to(ROOT)),
                "bytes": len(raw),
                "sha256": sha256_bytes(raw),
            }
        )

    mismatch_records = [
        {
            "directory_name": record["directory_name"],
            "head_matches_manifest": record["head_matches_manifest"],
            "origin_matches_manifest": record["origin_matches_manifest"],
        }
        for record in records
        if record["head_matches_manifest"] is False
        or record["origin_matches_manifest"] is False
    ]

    report = {
        "schema_version": "EffectiveDependencySource/1",
        "repository_head": text(["git", "rev-parse", "HEAD"], cwd=ROOT),
        "repository_tree": text(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT),
        "lean_toolchain": (LEAN_ROOT / "lean-toolchain").read_text(
            encoding="utf-8"
        ).strip(),
        "identity_files": {
            "lean/lakefile.lean": sha256_file(LEAN_ROOT / "lakefile.lean"),
            "lean/lake-manifest.json": sha256_file(manifest_path),
            "lean/lean-toolchain": sha256_file(LEAN_ROOT / "lean-toolchain"),
        },
        "manifest_git_package_count": len(expected_packages),
        "observed_git_package_count": len(records),
        "missing_expected_packages": missing_expected,
        "unexpected_observed_packages": unexpected_observed,
        "manifest_identity_mismatches": mismatch_records,
        "packages": records,
        "ordered_patch_inventory": patches,
        "limits": [
            "The effective Git tree is computed from a temporary index after Lake update.",
            "Ignored build outputs are excluded from the effective source tree.",
            "This manifest identifies bytes; it does not establish semantic equivalence of a patch.",
        ],
    }
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    summary = {
        "output": str(output.relative_to(ROOT)),
        "output_sha256": sha256_file(output),
        "observed_git_package_count": len(records),
        "dirty_package_count": sum(
            1 for record in records if record["status_entry_count"]
        ),
        "missing_expected_packages": missing_expected,
        "unexpected_observed_packages": unexpected_observed,
        "manifest_identity_mismatches": mismatch_records,
        "patch_count": len(patches),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))

    return 1 if missing_expected or mismatch_records else 0


if __name__ == "__main__":
    raise SystemExit(main())
