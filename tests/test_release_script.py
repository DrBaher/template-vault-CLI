"""Tests for scripts/release.py.

Exercises the file-mutation functions against temp copies (never the
real working tree). The git-commit/tag step is exercised via --dry-run
+ a separate git-CLI integration smoke (skipped on machines without
git).
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any, cast

# Load scripts/release.py as a module without putting `scripts/` on sys.path.
_RELEASE_PY = Path(__file__).resolve().parent.parent / "scripts" / "release.py"


def _load_release() -> Any:
    spec = importlib.util.spec_from_file_location("release", str(_RELEASE_PY))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


release = _load_release()


class VersionFormatTests(unittest.TestCase):
    def test_accepts_canonical_xyz(self):
        self.assertTrue(release.check_version_format("0.5.0"))
        self.assertTrue(release.check_version_format("1.0.0"))
        self.assertTrue(release.check_version_format("12.34.56"))

    def test_rejects_non_canonical(self):
        self.assertFalse(release.check_version_format("v0.5.0"))
        self.assertFalse(release.check_version_format("0.5"))
        self.assertFalse(release.check_version_format("0.5.0-rc1"))
        self.assertFalse(release.check_version_format("not-a-version"))


class UpdatePyprojectTests(unittest.TestCase):
    def test_replaces_top_level_version(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pyproject.toml"
            p.write_text(
                '[project]\n'
                'name = "x"\n'
                'version = "0.4.0"\n'
                'description = "y"\n'
            )
            self.assertTrue(release.update_pyproject(p, "0.5.0"))
            self.assertIn('version = "0.5.0"', p.read_text())
            self.assertNotIn('"0.4.0"', p.read_text())

    def test_returns_false_when_no_version_line(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pyproject.toml"
            p.write_text("[project]\nname = \"x\"\n")
            self.assertFalse(release.update_pyproject(p, "0.5.0"))


class UpdateVersionInPythonTests(unittest.TestCase):
    def test_replaces_dunder_version(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cli.py"
            p.write_text('"""module"""\n__version__ = "0.4.0"\nx = 1\n')
            self.assertTrue(release.update_version_in_python(p, "0.5.0"))
            self.assertIn('__version__ = "0.5.0"', p.read_text())


class PromoteChangelogTests(unittest.TestCase):
    def test_promotes_unreleased_to_dated_version_heading(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "CHANGELOG.md"
            p.write_text(
                "# Changelog\n\n"
                "## Unreleased\n\n"
                "- Some change\n\n"
                "## 0.4.0 — 2026-05-11\n\n"
                "Previous release.\n"
            )
            self.assertTrue(release.promote_changelog(
                p, "0.5.0", today_iso="2026-05-19"))
            text = p.read_text()
            self.assertIn("## 0.5.0 — 2026-05-19", text)
            self.assertNotIn("## Unreleased", text)
            # Don't touch the previous release heading.
            self.assertIn("## 0.4.0 — 2026-05-11", text)

    def test_refuses_when_no_unreleased_section(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "CHANGELOG.md"
            p.write_text(
                "# Changelog\n\n"
                "## 0.4.0 — 2026-05-11\n\n"
                "Previous release with no Unreleased above it.\n"
            )
            self.assertFalse(release.promote_changelog(
                p, "0.5.0", today_iso="2026-05-19"))
            # File unchanged.
            self.assertNotIn("## 0.5.0", p.read_text())


class CurrentPyprojectVersionTests(unittest.TestCase):
    def test_returns_version_string(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pyproject.toml"
            p.write_text('[project]\nname = "x"\nversion = "0.4.0"\n')
            self.assertEqual(release.current_pyproject_version(p), "0.4.0")

    def test_returns_none_when_absent(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pyproject.toml"
            p.write_text("[project]\nname = \"x\"\n")
            self.assertIsNone(release.current_pyproject_version(p))


class DryRunMainTests(unittest.TestCase):
    """End-to-end dry-run: build a fake repo layout in a temp dir,
    invoke release.main([...]), assert no files changed."""

    def test_dry_run_changes_nothing(self):
        import io
        import tempfile
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "x"\nversion = "0.4.0"\n'
            )
            (root / "template_vault_cli.py").write_text(
                '"""m"""\n__version__ = "0.4.0"\n'
            )
            (root / "CHANGELOG.md").write_text(
                "# Changelog\n\n## Unreleased\n\n- x\n"
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = release.main(["0.5.0", "--dry-run", "--repo-root", str(root)])
            self.assertEqual(rc, 0)
            self.assertIn("Would release 0.5.0", buf.getvalue())
            # Files untouched.
            self.assertIn('"0.4.0"', (root / "pyproject.toml").read_text())
            self.assertIn("## Unreleased", (root / "CHANGELOG.md").read_text())

    def test_refuses_bad_version(self):
        rc = release.main(["not-a-version", "--dry-run",
                            "--repo-root", str(_RELEASE_PY.parent.parent)])
        self.assertNotEqual(rc, 0)

    def test_refuses_when_already_at_that_version(self):
        import io
        import tempfile
        from contextlib import redirect_stderr

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "x"\nversion = "0.5.0"\n'
            )
            (root / "template_vault_cli.py").write_text('__version__ = "0.5.0"\n')
            (root / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n")
            err = io.StringIO()
            with redirect_stderr(err):
                rc = release.main(["0.5.0", "--repo-root", str(root)])
            self.assertNotEqual(rc, 0)
            self.assertIn("already at 0.5.0", err.getvalue())


if __name__ == "__main__":
    unittest.main()
