"""Verify the installed package launches outside the repository."""

import os
import subprocess
import sys
import tempfile
import unittest


class InstalledPackageTests(unittest.TestCase):
    def test_module_entry_point(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-m", "lbe"],
                cwd=directory,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=os.environ | {"PYTHONIOENCODING": "utf-8"},
                timeout=10,
                check=True,
            )
        self.assertIn("LittleBigEngine (LBE)", result.stdout)
        self.assertIn("not implemented yet", result.stdout)
        self.assertEqual(result.stderr, "")
