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
                [sys.executable, "-m", "lbe", "--check"],
                cwd=directory,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=os.environ | {"PYTHONIOENCODING": "utf-8"},
                timeout=10,
                check=True,
            )
        self.assertIn("LittleBigEngine (LBE)", result.stdout)
        self.assertIn("core ready", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_direct_main_check(self):
        import io
        from unittest.mock import patch
        from lbe.__main__ import main

        f = io.StringIO()
        with patch("sys.argv", ["lbe", "--check"]), patch("sys.stdout", f):
            main()
        self.assertIn("LittleBigEngine (LBE)", f.getvalue())
        self.assertIn("core ready", f.getvalue())

    def test_direct_main_invalid_frames(self):
        import io
        from unittest.mock import patch
        from lbe.__main__ import main

        with patch("sys.argv", ["lbe", "--frames", "0"]), patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                main()

