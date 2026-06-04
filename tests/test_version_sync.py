"""template_vault_cli.__version__ must match the pyproject.toml version.

A hardcoded module version that drifts from the package version makes
`--version` and `--catalog json` under-report (this bit extract-cli once). The
release script bumps both, but nothing asserted they stay equal — this does.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import template_vault_cli as tvc  # noqa: E402


class VersionSyncTest(unittest.TestCase):
    def test_version_matches_pyproject(self) -> None:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
        self.assertIsNotNone(m, "could not find version in pyproject.toml")
        self.assertEqual(
            m.group(1),
            tvc.__version__,
            "pyproject version must match template_vault_cli.__version__",
        )


if __name__ == "__main__":
    unittest.main()
