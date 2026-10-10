#!/usr/bin/env python3
"""Run one bounded Lean theorem probe and emit an immutable receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LEAN_ROOT = ROOT / "lean"
ALLOWED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def run_text(args: list[str], *, cwd: Path) -> str:
    proc = subprocess.run(
        args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
    )
    if proc.returncode != 0:
        return f"<failed:{proc.returncode}> {proc.stderr.strip()}"
    return proc.stdout.strip()


def stream_command(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
) -> dict[str, Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    with log_path.open("wb") as log:
        header = f"$ {' '.join(args)}\n".encode("utf-8")
        log.write(header)
        sys.stdout.buffer.write(header)
        sys.stdout.buffer.flush()
        proc = subprocess.Popen(
            args,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.readline()
            if not chunk:
                break
            log.write(chunk)
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
        exit_code = proc.wait()
    elapsed = time.monotonic() - start
    return {
        "command": args,
        "cwd": str(cwd.relative_to(ROOT)),
        "exit_code": exit_code,
        "elapsed_seconds": round(elapsed, 6),
        "log_path": str(log_path.relative_to(ROOT)),
        "log_sha256": sha256_file(log_path),
        "log_bytes": log_path.stat().st_size,
    }


def parse_axioms(output: str) -> tuple[list[str] | None, str | None]:
    matches = re.findall(r"depends on axioms:\s*\[([^\]]*)\]", output)
    if len(matches) != 1:
        return None, f"expected one '#print axioms' result, found {len(matches)}"
    payload = matches[0].strip()
    if not payload:
        return [], None
    axioms = sorted({item.strip() for item in payload.split(",") if item.strip()})
    return axioms, None


def skipped(name: str, reason: str) -> dict[str, Any]:
    return {
        "command": [],
        "cwd": "lean",
        "exit_code": None,
        "elapsed_seconds": 0,
        "log_path": None,
        "log_sha256": None,
        "log_bytes": 0,
        "status": "SKIPPED",
        "name": name,
        "reason": reason,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", required=True)
    parser.add_argument("--module", required=True)
    parser.add_argument("--theorem", required=True)
    parser.add_argument("--probe", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    probe_path = (ROOT / args.probe).resolve()
    output_dir = (ROOT / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if not probe_path.exists():
        raise SystemExit(f"probe file does not exist: {probe_path}")

    env = os.environ.copy()
    env.update(
        {
            "LEAN_ABORT_ON_PANIC": "1",
            "LEAN_NUM_THREADS": "1",
            "GLIBC_TUNABLES": (
                "glibc.malloc.mmap_max=0:glibc.malloc.arena_max=1"
            ),
        }
    )

    identity = {
        "repository_head": run_text(["git", "rev-parse", "HEAD"], cwd=ROOT),
        "repository_tree": run_text(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT
        ),
        "lean_version_before_update": run_text(["lean", "--version"], cwd=LEAN_ROOT),
        "lake_version_before_update": run_text(["lake", "--version"], cwd=LEAN_ROOT),
        "lean_toolchain": (LEAN_ROOT / "lean-toolchain").read_text(
            encoding="utf-8"
        ).strip(),
        "probe_path": str(probe_path.relative_to(ROOT)),
        "probe_sha256": sha256_file(probe_path),
        "runner_path": str(Path(__file__).relative_to(ROOT)),
        "runner_sha256": sha256_file(Path(__file__)),
    }

    commands: dict[str, dict[str, Any]] = {}
    commands["lake_update"] = stream_command(
        ["lake", "update"],
        cwd=LEAN_ROOT,
        env=env,
        log_path=output_dir / "lake-update.log",
    )

    dependency_manifest_path = output_dir / "effective-dependencies.json"
    if commands["lake_update"]["exit_code"] == 0:
        commands["dependency_manifest"] = stream_command(
            [
                sys.executable,
                str(ROOT / "audit/tools/effective_dependency_manifest.py"),
                "--output",
                str(dependency_manifest_path.relative_to(ROOT)),
            ],
            cwd=ROOT,
            env=env,
            log_path=output_dir / "effective-dependencies.log",
        )
        commands["mathlib_cache"] = stream_command(
            ["lake", "exe", "cache", "get"],
            cwd=LEAN_ROOT,
            env=env,
            log_path=output_dir / "mathlib-cache.log",
        )
        commands["module_build"] = stream_command(
            ["lake", "build", args.module],
            cwd=LEAN_ROOT,
            env=env,
            log_path=output_dir / "module-build.log",
        )
    else:
        commands["dependency_manifest"] = skipped(
            "dependency_manifest", "lake update failed"
        )
        commands["mathlib_cache"] = skipped("mathlib_cache", "lake update failed")
        commands["module_build"] = skipped("module_build", "lake update failed")

    if commands["module_build"].get("exit_code") == 0:
        relative_probe = os.path.relpath(probe_path, LEAN_ROOT)
        commands["lean_probe"] = stream_command(
            ["lake", "env", "lean", relative_probe],
            cwd=LEAN_ROOT,
            env=env,
            log_path=output_dir / "lean-probe.log",
        )
    else:
        commands["lean_probe"] = skipped("lean_probe", "module build failed")

    probe_output = ""
    probe_log = output_dir / "lean-probe.log"
    if probe_log.exists():
        probe_output = probe_log.read_text(encoding="utf-8", errors="replace")
    observed_axioms, axiom_parse_error = parse_axioms(probe_output)
    unexpected_axioms = (
        sorted(set(observed_axioms) - ALLOWED_AXIOMS)
        if observed_axioms is not None
        else []
    )
    missing_expected_axioms = (
        sorted(ALLOWED_AXIOMS - set(observed_axioms))
        if observed_axioms is not None
        else []
    )

    blocking_failures: list[str] = []
    for name in ("lake_update", "dependency_manifest", "module_build", "lean_probe"):
        if commands[name].get("exit_code") != 0:
            blocking_failures.append(f"{name} did not complete successfully")
    if axiom_parse_error:
        blocking_failures.append(axiom_parse_error)
    if unexpected_axioms:
        blocking_failures.append(f"unexpected axioms: {unexpected_axioms}")

    repository_status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    ).stdout

    receipt = {
        "schema_version": "SelectedTheoremKernelProbe/1",
        "key": args.key,
        "module": args.module,
        "theorem": args.theorem,
        "identity": identity,
        "commands": commands,
        "cache_status_is_evidence_only": True,
        "mathlib_cache_exit_code": commands["mathlib_cache"].get("exit_code"),
        "effective_dependency_manifest": (
            {
                "path": str(dependency_manifest_path.relative_to(ROOT)),
                "sha256": sha256_file(dependency_manifest_path),
            }
            if dependency_manifest_path.exists()
            else None
        ),
        "observed_axioms": observed_axioms,
        "allowed_axioms": sorted(ALLOWED_AXIOMS),
        "unexpected_axioms": unexpected_axioms,
        "allowed_axioms_not_observed": missing_expected_axioms,
        "axiom_parse_error": axiom_parse_error,
        "probe_output_sha256": (
            sha256_file(probe_log) if probe_log.exists() else None
        ),
        "repository_status_after_probe": repository_status.decode(
            "utf-8", "surrogateescape"
        ).splitlines(),
        "blocking_failures": blocking_failures,
        "classification": (
            "PRIMARY_KERNEL_PROBE_PASSED"
            if not blocking_failures
            else "PRIMARY_KERNEL_PROBE_INCOMPLETE_OR_FAILED"
        ),
        "limits": [
            "This is a primary Lean elaboration/kernel probe, not Comparator.",
            "Dependency cache use is recorded and does not imply a fresh dependency build.",
            "No independent kernel is invoked by this receipt.",
            "Axiom output is parsed from Lean's '#print axioms' command.",
        ],
    }
    receipt_path = output_dir / "kernel-probe-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    summary = {
        "key": args.key,
        "classification": receipt["classification"],
        "observed_axioms": observed_axioms,
        "unexpected_axioms": unexpected_axioms,
        "blocking_failures": blocking_failures,
        "receipt": str(receipt_path.relative_to(ROOT)),
        "receipt_sha256": sha256_file(receipt_path),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if blocking_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
