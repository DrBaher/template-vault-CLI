#!/usr/bin/env python3
"""Bump version + promote CHANGELOG + commit + tag in one step.

Usage:
    python scripts/release.py 0.5.0
    python scripts/release.py 0.5.0 --dry-run
    python scripts/release.py 0.5.0 --no-tag

Or via the Makefile:
    make release VERSION=0.5.0

What it does:
    1. Validates the version matches X.Y.Z.
    2. Refuses to run with a dirty working tree.
    3. Refuses to re-release a version that already matches pyproject.
    4. Updates pyproject.toml's `version` field.
    5. Updates template_vault_cli.py's `__version__`.
    6. Promotes CHANGELOG's `## Unreleased` heading to `## X.Y.Z — <date>`.
       Refuses if there's no Unreleased section to promote.
    7. git-commits the three files with message `release: X.Y.Z`.
    8. Tags vX.Y.Z (unless --no-tag).
    9. Prints next-step instructions.

Stdlib-only by design (the rest of the project is too). Tests for the
file-mutation functions live in tests/test_release_script.py and run
against temp copies, never the real working tree.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


def _fail(msg: str) -> "Optional[int]":
    print(f"release: error: {msg}", file=sys.stderr)
    return 1


def check_version_format(v: str) -> bool:
    """Return True if v looks like X.Y.Z. Tolerates `vX.Y.Z` by stripping
    the leading v (callers should pass without v)."""
    return bool(re.fullmatch(r"\d+\.\d+\.\d+", v))


def working_tree_dirty(repo_root: Path) -> bool:
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo_root), capture_output=True, text=True,
    )
    return bool(r.stdout.strip())


def update_pyproject(path: Path, new_version: str) -> bool:
    """Replace the top-level `version = "..."` line. Returns True if the
    file changed."""
    text = path.read_text(encoding="utf-8")
    new_text, n = re.subn(
        r'^version\s*=\s*"[^"]+"',
        f'version = "{new_version}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if n != 1:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def update_version_in_python(path: Path, new_version: str) -> bool:
    """Replace the top-level `__version__ = "..."` line. Returns True if
    the file changed."""
    text = path.read_text(encoding="utf-8")
    new_text, n = re.subn(
        r'^__version__\s*=\s*"[^"]+"',
        f'__version__ = "{new_version}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if n != 1:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def promote_changelog(path: Path, new_version: str,
                      today_iso: Optional[str] = None) -> bool:
    """Replace `## Unreleased` (top of the changelog body) with
    `## X.Y.Z — <today>`. Returns True if the file changed.

    Refuses if the file has no Unreleased heading -- callers must add
    one before running the release script.
    """
    text = path.read_text(encoding="utf-8")
    new_heading = (
        f"## {new_version} — "
        f"{today_iso or _dt.date.today().isoformat()}"
    )
    new_text, n = re.subn(
        r"^## Unreleased\s*$",
        new_heading,
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if n != 1:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def current_pyproject_version(path: Path) -> Optional[str]:
    text = path.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    return m.group(1) if m else None


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="release.py",
        description="Bump version, promote CHANGELOG, commit, tag.",
    )
    p.add_argument("version", help="X.Y.Z version to release")
    p.add_argument("--dry-run", action="store_true",
                   help="Show the plan; don't write or commit anything.")
    p.add_argument("--no-tag", action="store_true",
                   help="Commit but don't create the git tag.")
    p.add_argument("--repo-root", default=None,
                   help="Override repo root (default: parent of this script's dir).")
    args = p.parse_args(argv)

    version = args.version.lstrip("v")
    if not check_version_format(version):
        return _fail(f"version {args.version!r} must be X.Y.Z") or 1

    if args.repo_root:
        root = Path(args.repo_root).resolve()
    else:
        root = Path(__file__).resolve().parent.parent

    pyproject = root / "pyproject.toml"
    cli_py = root / "template_vault_cli.py"
    changelog = root / "CHANGELOG.md"
    for required in (pyproject, cli_py, changelog):
        if not required.exists():
            return _fail(f"missing required file: {required}") or 1

    current = current_pyproject_version(pyproject)
    if current == version:
        return _fail(
            f"pyproject.toml is already at {version}. "
            f"Pick a new version or amend the previous release."
        ) or 1

    if not args.dry_run and working_tree_dirty(root):
        return _fail(
            "working tree is dirty. Commit or stash before releasing."
        ) or 1

    plan = [
        f"  pyproject.toml: version {current} -> {version}",
        f"  template_vault_cli.py: __version__ = '{version}'",
        f"  CHANGELOG.md: '## Unreleased' -> '## {version} -- {_dt.date.today().isoformat()}'",
        f"  git commit -m 'release: {version}'",
    ]
    if not args.no_tag:
        plan.append(f"  git tag v{version}")

    if args.dry_run:
        print(f"Would release {version}:")
        for line in plan:
            print(line)
        return 0

    if not update_pyproject(pyproject, version):
        return _fail("could not update pyproject.toml's version field") or 1
    if not update_version_in_python(cli_py, version):
        return _fail("could not update __version__ in template_vault_cli.py") or 1
    if not promote_changelog(changelog, version):
        return _fail(
            "CHANGELOG.md has no '## Unreleased' section to promote. "
            "Add one (with the changes for this release) and re-run."
        ) or 1

    subprocess.run(
        ["git", "add", str(pyproject), str(cli_py), str(changelog)],
        cwd=str(root), check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", f"release: {version}"],
        cwd=str(root), check=True,
    )
    if not args.no_tag:
        subprocess.run(
            ["git", "tag", f"v{version}"],
            cwd=str(root), check=True,
        )

    print(f"Released {version}. Next:")
    print(f"  git push origin main")
    if not args.no_tag:
        print(f"  git push origin v{version}    "
              f"# triggers PyPI publish via .github/workflows/publish.yml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
