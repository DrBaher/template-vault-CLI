"""Regression tests for the 2026-06 source-audit fixes.

Covers:
  - resolve_version_file: a hand-edited meta.json whose version id contains
    `../` is rejected and never reads/writes outside the vault root;
  - upload --version / --amend: a traversal id is rejected and nothing is
    written outside the vault root;
  - ask --top-k rejects negatives (sibling of the find hardening);
  - history: a non-dict element in versions[]/clause_overrides[] yields a clean
    VaultError, not the generic "unexpected" backstop.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests._helpers import (
    CliCase, add_template, run_cli, temp_vault, tvc, SAMPLE_NDA_MUTUAL,
)


class ResolveVersionTraversalTests(CliCase):
    def _make_template_with_version(self, vault: Path, vid: str) -> Path:
        t = vault / "nda" / "house"
        t.mkdir(parents=True)
        (t / "v1.md").write_text(SAMPLE_NDA_MUTUAL)
        meta = {
            "name": "house", "category": "nda",
            "latest_version": vid,
            "versions": [{"id": vid, "added": tvc._today_iso(),
                          "supersedes": None, "changelog": "x"}],
        }
        tvc.save_meta(t, tvc.fill_meta_defaults(meta))
        return t

    def test_resolve_version_rejects_traversal_id(self):
        with temp_vault() as v:
            t = self._make_template_with_version(Path(v), "../../../etc/passwd")
            meta = tvc.load_meta(t)
            with self.assertRaises(tvc.VaultError):
                tvc.resolve_version_file(t, meta, None)

    def test_get_with_traversal_latest_version_is_clean_error(self):
        with temp_vault() as v:
            self._make_template_with_version(Path(v), "../../../etc/passwd")
            code, _out, err = run_cli("get", "nda/house")
            self.assertEqual(code, 2)
            self.assertIn("Invalid", err)
            self.assertNotIn("Traceback", err)

    def test_resolve_version_explicit_traversal_rejected(self):
        # Even when the id is "present" in versions[], it must not escape t_dir.
        with temp_vault() as v:
            t = self._make_template_with_version(Path(v), "../escape")
            meta = tvc.load_meta(t)
            with self.assertRaises(tvc.VaultError):
                tvc.resolve_version_file(t, meta, "../escape")
            # Nothing was created outside the vault.
            self.assertFalse((Path(v).resolve().parent / "escape.md").exists())


class UploadVersionTraversalTests(CliCase):
    def test_upload_version_cannot_escape_vault(self):
        with temp_vault() as v:
            src = Path(v) / "src.md"
            src.write_text(SAMPLE_NDA_MUTUAL)
            escape = Path(v).resolve().parent / "tvescape.md"
            code, _out, err = run_cli(
                "upload", str(src),
                "--category", "nda", "--name", "house",
                "--version", "../../tvescape",
                "--summary", "s", "--non-interactive",
            )
            self.assertEqual(code, 2)
            self.assertIn("Invalid", err)
            self.assertFalse(escape.exists())

    def test_upload_amend_version_cannot_escape_vault(self):
        with temp_vault() as v:
            add_template(Path(v), "nda", "house", SAMPLE_NDA_MUTUAL)
            src = Path(v) / "src.md"
            src.write_text(SAMPLE_NDA_MUTUAL)
            escape = Path(v).resolve().parent / "tvescape.md"
            code, _out, err = run_cli(
                "upload", str(src),
                "--category", "nda", "--name", "house",
                "--amend", "../../tvescape",
                "--summary", "s", "--non-interactive", "--yes-amend",
            )
            self.assertEqual(code, 2)
            self.assertIn("Invalid", err)
            self.assertFalse(escape.exists())


class AskTopKTests(CliCase):
    def test_ask_rejects_negative_top_k(self):
        with temp_vault() as v:
            add_template(Path(v), "nda", "a", SAMPLE_NDA_MUTUAL)
            code, _out, err = run_cli("ask", "purpose", "--top-k", "-1")
            self.assertEqual(code, 2)
            self.assertIn("top-k", err)
            self.assertNotIn("Traceback", err)


class HistoryMalformedMetaTests(CliCase):
    def _write_meta(self, vault: Path, meta: dict) -> Path:
        t = vault / "nda" / "house"
        t.mkdir(parents=True)
        (t / "v1.md").write_text(SAMPLE_NDA_MUTUAL)
        (t / tvc.META_FILENAME).write_text(json.dumps(meta))
        return t

    def test_history_non_dict_version_is_clean_error(self):
        with temp_vault() as v:
            self._write_meta(Path(v), {
                "name": "house", "category": "nda",
                "latest_version": "v1",
                "versions": ["not-an-object",
                             {"id": "v1", "added": tvc._today_iso()}],
            })
            code, _out, err = run_cli("history", "nda/house")
            self.assertEqual(code, 2)
            self.assertIn("Malformed", err)
            self.assertNotIn("unexpected", err)
            self.assertNotIn("Traceback", err)

    def test_history_json_non_dict_override_is_clean_error(self):
        with temp_vault() as v:
            self._write_meta(Path(v), {
                "name": "house", "category": "nda",
                "latest_version": "v1",
                "versions": [{"id": "v1", "added": tvc._today_iso()}],
                "clause_overrides": ["bad"],
            })
            code, _out, err = run_cli("history", "nda/house", "--json")
            self.assertEqual(code, 2)
            self.assertIn("Malformed", err)
            self.assertNotIn("unexpected", err)
            self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
