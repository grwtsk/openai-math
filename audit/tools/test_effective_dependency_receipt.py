#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).with_name("effective_dependency_receipt.py")
SPEC = importlib.util.spec_from_file_location("effective_dependency_receipt", MODULE)
assert SPEC and SPEC.loader
DEP = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DEP
SPEC.loader.exec_module(DEP)


class EffectiveTreeTests(unittest.TestCase):
    def git(self, path: Path, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=path, text=True).strip()

    def make_repo(self, path: Path) -> None:
        self.git(path, "init", "-q")
        self.git(path, "config", "user.email", "audit@example.invalid")
        self.git(path, "config", "user.name", "Audit")
        (path / "A.lean").write_text("def a := 1\n")
        self.git(path, "add", "A.lean")
        self.git(path, "commit", "-qm", "base")

    def test_effective_tree_equals_head_when_clean(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)
            self.make_repo(path)
            self.assertEqual(DEP.effective_tree(path), self.git(path, "rev-parse", "HEAD^{tree}"))

    def test_effective_tree_changes_for_modified_and_untracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)
            self.make_repo(path)
            head_tree = self.git(path, "rev-parse", "HEAD^{tree}")
            (path / "A.lean").write_text("def a := 2\n")
            (path / "B.lean").write_text("def b := 3\n")
            self.assertNotEqual(DEP.effective_tree(path), head_tree)

    def test_quoted_manifest_identifier_maps_to_directory(self) -> None:
        self.assertEqual(DEP.package_directory_name("«doc-gen4»"), "doc-gen4")
        self.assertEqual(DEP.package_directory_name("mathlib"), "mathlib")


if __name__ == "__main__":
    unittest.main(verbosity=2)
