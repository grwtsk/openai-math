#!/usr/bin/env python3
"""Hostile tests for effective_dependency_manifest.py."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("effective_dependency_manifest.py")
SPEC = importlib.util.spec_from_file_location(
    "effective_dependency_manifest", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
MANIFEST = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MANIFEST
SPEC.loader.exec_module(MANIFEST)


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        text=True,
    )
    return proc.stdout.strip()


class NameNormalizationTests(unittest.TestCase):
    def test_guillemet_escaped_lake_names(self) -> None:
        self.assertEqual(
            MANIFEST.normalize_manifest_name("«formal-schemes»"),
            "formal-schemes",
        )
        self.assertEqual(MANIFEST.normalize_manifest_name("mathlib"), "mathlib")


class TemporaryIndexTests(unittest.TestCase):
    def test_effective_tree_includes_changes_without_mutating_real_index(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            git(repo, "init", "-q")
            git(repo, "config", "user.name", "Audit Test")
            git(repo, "config", "user.email", "audit@example.invalid")
            (repo / "tracked.txt").write_text("before\n", encoding="utf-8")
            git(repo, "add", "tracked.txt")
            git(repo, "commit", "-q", "-m", "initial")
            head_tree = git(repo, "rev-parse", "HEAD^{tree}")

            (repo / "tracked.txt").write_text("after\n", encoding="utf-8")
            (repo / "untracked.txt").write_text("new\n", encoding="utf-8")
            status_before = git(repo, "status", "--porcelain=v1", "--untracked-files=all")
            cached_before = git(repo, "diff", "--cached", "--name-only")

            effective_tree = MANIFEST.temporary_index_tree(repo)

            status_after = git(repo, "status", "--porcelain=v1", "--untracked-files=all")
            cached_after = git(repo, "diff", "--cached", "--name-only")
            self.assertNotEqual(effective_tree, head_tree)
            self.assertEqual(status_after, status_before)
            self.assertEqual(cached_before, "")
            self.assertEqual(cached_after, "")

    def test_ignored_build_output_is_not_added_to_effective_source_tree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            git(repo, "init", "-q")
            git(repo, "config", "user.name", "Audit Test")
            git(repo, "config", "user.email", "audit@example.invalid")
            (repo / ".gitignore").write_text("build/\n", encoding="utf-8")
            (repo / "source.txt").write_text("source\n", encoding="utf-8")
            git(repo, "add", ".gitignore", "source.txt")
            git(repo, "commit", "-q", "-m", "initial")
            head_tree = git(repo, "rev-parse", "HEAD^{tree}")
            (repo / "build").mkdir()
            (repo / "build" / "artifact.bin").write_bytes(b"ignored")
            self.assertEqual(MANIFEST.temporary_index_tree(repo), head_tree)


class StableIdentityTests(unittest.TestCase):
    def test_sha256_is_byte_sensitive(self) -> None:
        self.assertNotEqual(
            MANIFEST.sha256_bytes(b"a\n"),
            MANIFEST.sha256_bytes(b"a\r\n"),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
