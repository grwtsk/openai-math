#!/usr/bin/env python3
"""Record nominal and post-patch Git-tree identities for Lake packages.

The effective source of a patched Lake dependency is not just its manifest
revision. It is the checked-out commit plus every tracked and untracked source
byte present after Lake's patch hooks have run. This scanner constructs a Git
tree from the non-ignored worktree without modifying the package checkout.
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


def command(
    cwd: Path,
    *args: str,
    env: dict[str, str] | None = None,
    binary: bool = False,
) -> str | bytes:
    return subprocess.check_output(
        args,
        cwd=cwd,
        env=env,
        text=not binary,
        stderr=subprocess.STDOUT,
    ).strip()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_optional(cwd: Path, *args: str) -> str | None:
    try:
        value = command(cwd, "git", *args)
        assert isinstance(value, str)
        return value
    except subprocess.CalledProcessError:
        return None


def nul_paths(raw: bytes) -> list[str]:
    return [item.decode("utf-8", "surrogateescape") for item in raw.split(b"\0") if item]


def package_directory_name(name: str) -> str:
    """Convert a manifest Lean identifier to Lake's package directory name."""
    if name.startswith("«") and name.endswith("»") and len(name) >= 2:
        return name[1:-1]
    return name


def file_record(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    raw = path.read_bytes()
    return {
        "path": relative,
        "bytes": len(raw),
        "sha256": sha256_bytes(raw),
    }


def effective_tree(repo: Path) -> str:
    """Hash the non-ignored worktree as a Git tree through a temporary index."""
    with tempfile.TemporaryDirectory() as td:
        index = Path(td) / "index"
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(index)
        subprocess.run(
            ["git", "read-tree", "HEAD"],
            cwd=repo,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "add", "-A", "--", "."],
            cwd=repo,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        value = command(repo, "git", "write-tree", env=env)
        assert isinstance(value, str)
        return value


def package_record(path: Path, manifest_entry: dict[str, Any] | None) -> dict[str, Any]:
    raw_status = command(path, "git", "status", "--porcelain=v1", "-z", binary=True)
    assert isinstance(raw_status, bytes)
    tracked_diff = command(path, "git", "diff", "--binary", "HEAD", binary=True)
    assert isinstance(tracked_diff, bytes)
    changed_raw = command(path, "git", "diff", "--name-only", "-z", "HEAD", binary=True)
    assert isinstance(changed_raw, bytes)
    untracked_raw = command(
        path,
        "git",
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        binary=True,
    )
    assert isinstance(untracked_raw, bytes)

    changed_paths = sorted(nul_paths(changed_raw))
    untracked_paths = sorted(nul_paths(untracked_raw))
    untracked_files = [file_record(path, relative) for relative in untracked_paths]

    head = git_optional(path, "rev-parse", "HEAD")
    head_tree = git_optional(path, "rev-parse", "HEAD^{tree}")
    result_tree = effective_tree(path)
    manifest_rev = manifest_entry.get("rev") if isinstance(manifest_entry, dict) else None
    return {
        "package_directory": path.name,
        "origin": git_optional(path, "remote", "get-url", "origin"),
        "head_commit": head,
        "head_tree": head_tree,
        "effective_tree": result_tree,
        "dirty": bool(raw_status),
        "status_sha256": sha256_bytes(raw_status),
        "tracked_binary_diff_sha256": sha256_bytes(tracked_diff),
        "changed_tracked_paths": changed_paths,
        "untracked_files": untracked_files,
        "manifest_name": manifest_entry.get("name") if isinstance(manifest_entry, dict) else None,
        "manifest_url": manifest_entry.get("url") if isinstance(manifest_entry, dict) else None,
        "manifest_revision": manifest_rev,
        "head_matches_manifest_revision": head == manifest_rev if isinstance(manifest_rev, str) else None,
        "effective_tree_equals_head_tree": result_tree == head_tree,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Effective Lake dependency source receipt",
        "",
        f"- Frozen source revision: `{report['frozen_base_revision']}`",
        f"- Frozen Lean tree: `{report['frozen_lean_tree']}`",
        f"- Audit head: `{report['audit_head_commit']}`",
        f"- Audit Lean tree: `{report['audit_lean_tree']}`",
        f"- Lean subtree matches frozen source: `{report['lean_subtree_matches_frozen_base']}`",
        f"- Lake packages observed: **{report['package_count']:,}**",
        f"- Modified package worktrees: **{report['dirty_package_count']:,}**",
        "",
        "## Package identities",
        "",
        "| Package | Manifest revision | HEAD | Effective tree | Modified |",
        "|---|---|---|---|---:|",
    ]
    for package in report["packages"]:
        lines.append(
            "| `{}` | `{}` | `{}` | `{}` | {} |".format(
                package["package_directory"],
                package["manifest_revision"],
                package["head_commit"],
                package["effective_tree"],
                "yes" if package["dirty"] else "no",
            )
        )
    lines += ["", "## Policy result", ""]
    if report["violations"]:
        for violation in report["violations"]:
            lines.append(f"- **{violation['code']}**: {violation['detail']}")
    else:
        lines.append("Every observed Git package HEAD matched its manifest revision.")
    lines += [
        "",
        "## Boundary",
        "",
        "The effective tree identifies the non-ignored package worktree after Lake patch hooks.",
        "It does not classify the mathematical meaning, authorship, license, or downstream use of a patch.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lean-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--frozen-base-revision", required=True)
    parser.add_argument("--frozen-base-tree", required=True)
    parser.add_argument("--frozen-lean-tree", required=True)
    parser.add_argument("--audit-head-commit", required=True)
    parser.add_argument("--audit-head-tree", required=True)
    parser.add_argument("--audit-lean-tree", required=True)
    args = parser.parse_args()

    manifest_path = args.lean_dir / "lake-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    packages = manifest.get("packages", []) if isinstance(manifest, dict) else []
    by_name = {
        package_directory_name(str(p.get("name"))): p
        for p in packages
        if isinstance(p, dict) and p.get("name")
    }

    package_root = args.lean_dir / ".lake" / "packages"
    records: list[dict[str, Any]] = []
    violations: list[dict[str, str]] = []
    for path in sorted(package_root.iterdir() if package_root.exists() else []):
        if not path.is_dir() or not (path / ".git").exists():
            continue
        entry = by_name.get(path.name)
        record = package_record(path, entry)
        records.append(record)
        if entry is None:
            violations.append({
                "code": "PACKAGE_NOT_IN_MANIFEST",
                "detail": f"{path.name}: checked-out Git package has no manifest entry by directory name",
            })
        if record["head_matches_manifest_revision"] is False:
            violations.append({
                "code": "PACKAGE_HEAD_MISMATCH",
                "detail": f"{path.name}: HEAD {record['head_commit']} != manifest {record['manifest_revision']}",
            })

    manifest_git_names = {
        package_directory_name(str(p.get("name")))
        for p in packages
        if isinstance(p, dict) and p.get("type") == "git" and p.get("name")
    }
    observed = {r["package_directory"] for r in records}
    missing = sorted(manifest_git_names - observed)
    if missing:
        violations.append({"code": "MANIFEST_PACKAGES_MISSING", "detail": repr(missing)})
    if args.audit_lean_tree != args.frozen_lean_tree:
        violations.append({
            "code": "LEAN_SUBTREE_DIFFERS_FROM_FROZEN_BASE",
            "detail": f"audit {args.audit_lean_tree} != frozen {args.frozen_lean_tree}",
        })

    report = {
        "schema_version": "EffectiveLakeDependencySource/1",
        "frozen_base_revision": args.frozen_base_revision,
        "frozen_base_tree": args.frozen_base_tree,
        "frozen_lean_tree": args.frozen_lean_tree,
        "audit_head_commit": args.audit_head_commit,
        "audit_head_tree": args.audit_head_tree,
        "audit_lean_tree": args.audit_lean_tree,
        "lean_subtree_matches_frozen_base": args.audit_lean_tree == args.frozen_lean_tree,
        "lake_manifest_sha256": sha256_bytes(manifest_path.read_bytes()),
        "lakefile_sha256": sha256_bytes((args.lean_dir / "lakefile.lean").read_bytes()),
        "lean_toolchain_sha256": sha256_bytes((args.lean_dir / "lean-toolchain").read_bytes()),
        "package_count": len(records),
        "dirty_package_count": sum(1 for r in records if r["dirty"]),
        "packages": records,
        "violations": violations,
        "limits": [
            "The effective tree hashes the non-ignored package worktree after Lake patch application.",
            "It does not by itself classify patch semantics, authorship, license compliance, or theorem usage.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "sha256": sha256_bytes(args.output.read_bytes()),
        "package_count": len(records),
        "dirty_package_count": report["dirty_package_count"],
        "violations": len(violations),
    }, indent=2, sort_keys=True))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
