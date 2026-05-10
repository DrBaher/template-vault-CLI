"""Shared test helpers: temp vault setup, sample template content, fake CLI runner."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

# Make the CLI importable regardless of CWD
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import template_vault_cli as tvc  # noqa: E402


SAMPLE_NDA_MUTUAL = """\
# Mutual NDA

Frontmatter / preamble text.

## 1. Purpose

The parties wish to evaluate a potential business relationship.

### 1.1 Scope

Limited to the evaluation period.

## 2. Definition of Confidential Information

Information disclosed by one party to the other that is marked as
confidential or that a reasonable person would understand to be
confidential.

## 3. Obligations

Each party shall protect the other's Confidential Information.

## 4. Term and Survival

This agreement terminates two years after the last disclosure. Confidentiality
obligations survive for three years after termination.

## 5. Residual Knowledge

Nothing in this agreement restricts the receiving party's use of residual
knowledge retained in the unaided memory of its representatives.
"""

SAMPLE_NDA_STARTUP_FRIENDLY = """\
# Startup-friendly NDA (YC-flavor)

## 1. Purpose

The parties are exploring a relationship.

## 2. Definition of Confidential Information

Trade secrets and information designated as confidential.

## 3. Obligations

Each party will use reasonable care.

## 4. Term and Survival

This agreement terminates one year from the Effective Date. Confidentiality
obligations survive for one year after termination.
"""

SAMPLE_LICENSING = """\
# Enterprise SaaS Licensing Template

## 1. License Grant

Vendor grants Customer a non-exclusive, non-transferable license.

## 2. Warranties

Vendor warrants the Service will perform materially as described in the
Documentation for ninety (90) days.

## 3. Limitation of Liability

Liability is capped at fees paid in the prior twelve months.
"""


def init_vault(path: Path) -> None:
    """Initialize a vault config without invoking git (avoids requiring git in CI)."""
    cfg = {
        "schema_version": tvc.SCHEMA_VERSION,
        "created": tvc._today_iso(),
        "defaults": {"license": "private"},
        "sources": [],
    }
    tvc.write_vault_config(path, cfg)


def add_template(vault: Path, category: str, name: str, body: str,
                 version: str = "v1",
                 jurisdiction: Optional[List[str]] = None,
                 tags: Optional[List[str]] = None,
                 deal_type: Optional[List[str]] = None,
                 party_type: Optional[List[str]] = None,
                 summary: str = "") -> Path:
    """Write a template directly (no upload command path)."""
    t_dir = vault / category / name
    t_dir.mkdir(parents=True, exist_ok=True)
    f = t_dir / f"{version}.md"
    f.write_text(body)
    meta = {
        "name": name,
        "category": category,
        "latest_version": version,
        "versions": [{
            "id": version,
            "added": tvc._today_iso(),
            "supersedes": None,
            "changelog": "test fixture",
        }],
    }
    meta = tvc.fill_meta_defaults(meta)
    meta["jurisdiction"] = list(jurisdiction or [])
    meta["tags"] = list(tags or [])
    meta["deal_type"] = list(deal_type or [])
    meta["party_type"] = list(party_type or [])
    meta["summary"] = summary or f"Test {category}/{name}"
    tvc.save_meta(t_dir, meta)
    return f


@contextmanager
def temp_vault() -> Iterator[Path]:
    """Yield a Path to a fresh, initialized vault. Switches CWD into it."""
    try:
        prev_cwd = Path.cwd()
    except (FileNotFoundError, OSError):
        prev_cwd = ROOT  # fall back to repo root
    with tempfile.TemporaryDirectory() as d:
        v = Path(d)
        init_vault(v)
        try:
            os.chdir(v)
            yield v
        finally:
            try:
                os.chdir(prev_cwd)
            except (FileNotFoundError, OSError):
                os.chdir(ROOT)


def run_cli(*argv: str) -> Tuple[int, str, str]:
    """Run the CLI in-process; return (exit_code, stdout, stderr)."""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = tvc.main(list(argv))
        except SystemExit as e:
            code = int(e.code) if e.code is not None else 0
    return code, out.getvalue(), err.getvalue()


class CliCase(unittest.TestCase):
    """Base TestCase with a common helper to assert clean exits."""

    def assertOk(self, result: Tuple[int, str, str], msg: str = "") -> None:
        code, out, err = result
        self.assertEqual(code, 0, f"{msg or 'CLI failed'}: code={code}, stderr={err!r}")
