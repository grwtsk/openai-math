#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).with_name("path_encoding_integrity.py")
SPEC = importlib.util.spec_from_file_location("path_encoding_integrity", MODULE)
assert SPEC and SPEC.loader
SCAN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SCAN
SPEC.loader.exec_module(SCAN)


class PathControlsTests(unittest.TestCase):
    def codes(self, findings):
        return {f.code for f in findings}

    def test_bidi_override_is_critical(self):
        findings = SCAN.control_findings("safe\u202eevil.lean", "safe\u202eevil.lean", content=False)
        self.assertIn("PATH_BIDI_CONTROL", self.codes(findings))
        self.assertTrue(any(f.severity == "critical" for f in findings))

    def test_zero_width_is_visible(self):
        findings = SCAN.control_findings("theorem\u200bname", "x.lean", content=True)
        self.assertIn("CONTENT_ZERO_WIDTH_CONTROL", self.codes(findings))

    def test_ordinary_mathematical_unicode_is_not_control(self):
        findings = SCAN.control_findings("theorem α_le_β : α ≤ β := h", "x.lean", content=True)
        self.assertEqual(findings, [])

    def test_edge_whitespace_and_reserved_names(self):
        # Win32 strips trailing spaces/dots before reserved-name resolution.
        codes = self.codes(SCAN.component_portability("lean/CON /file.lean"))
        self.assertIn("PATH_EDGE_WHITESPACE", codes)
        self.assertIn("WINDOWS_RESERVED_NAME", codes)

    def test_leading_space_is_not_silently_reclassified_as_reserved(self):
        codes = self.codes(SCAN.component_portability("lean/ CON/file.lean"))
        self.assertIn("PATH_EDGE_WHITESPACE", codes)
        self.assertNotIn("WINDOWS_RESERVED_NAME", codes)

    def test_trailing_dot(self):
        codes = self.codes(SCAN.component_portability("lean/OAI./X.lean"))
        self.assertIn("PATH_TRAILING_DOT", codes)

    def test_long_component(self):
        codes = self.codes(SCAN.component_portability("lean/" + "a" * 256 + ".lean"))
        self.assertIn("PATH_COMPONENT_TOO_LONG", codes)


class TextClassificationTests(unittest.TestCase):
    def test_lean_is_text(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "A.lean"
            p.write_text("theorem a : True := by trivial\n")
            self.assertTrue(SCAN.is_text_candidate(p, p.stat().st_size))

    def test_large_file_is_not_loaded_as_text(self):
        p = Path("A.lean")
        self.assertFalse(SCAN.is_text_candidate(p, 9 * 1024 * 1024))

    def test_pdf_is_not_text(self):
        p = Path("paper.pdf")
        self.assertFalse(SCAN.is_text_candidate(p, 10))


class StablePolicyTests(unittest.TestCase):
    def test_base_revision_is_full_sha(self):
        self.assertRegex(SCAN.BASE_REV, r"^[0-9a-f]{40}$")

    def test_controls_are_explicit(self):
        self.assertIn("\u202e", SCAN.BIDI_CONTROLS)
        self.assertIn("\u200b", SCAN.ZERO_WIDTH_CONTROLS)

    def test_windows_reserved_is_casefolded(self):
        self.assertIn("con", SCAN.WINDOWS_RESERVED)
        self.assertIn("com9", SCAN.WINDOWS_RESERVED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
