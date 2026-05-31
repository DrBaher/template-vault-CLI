"""Regression tests for the 0.5.2 source-audit robustness/durability fixes.

(The path-traversal and URL-scheme fixes from the same audit shipped in 0.5.1
and are covered by the security tests added there; this module covers the
remaining items.)

Covers:
  - a non-UTF-8 (binary/PDF) version body yields a clean VaultError, not a
    raw UnicodeDecodeError traceback;
  - `import` against a registry entry missing a required key raises VaultError;
  - `init` succeeds when `git` is absent (FileNotFoundError handled);
  - atomic writes leave no partial destination file on a mid-write crash;
  - main() has a top-level catch-all backstop;
  - find --top-k rejects negatives;
  - (sanity) traversal is still rejected and nothing is written outside root.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from tests._helpers import CliCase, add_template, run_cli, temp_vault, tvc


class NonUtf8BodyTests(CliCase):
    def _make_binary_template(self, vault: Path) -> None:
        t = vault / "nda" / "binary"
        t.mkdir(parents=True)
        (t / "v1.pdf").write_bytes(b"%PDF-1.4\n\xff\xfe\x00\x01 not utf8")
        meta = {
            "name": "binary", "category": "nda",
            "latest_version": "v1",
            "versions": [{"id": "v1", "added": tvc._today_iso(),
                          "supersedes": None, "changelog": "imported"}],
        }
        tvc.save_meta(t, tvc.fill_meta_defaults(meta))

    def test_get_on_binary_body_is_clean_vaulterror(self):
        with temp_vault() as v:
            self._make_binary_template(Path(v))
            code, _out, err = run_cli("get", "nda/binary")
            self.assertEqual(code, 2)
            self.assertIn("not valid UTF-8", err)
            self.assertNotIn("Traceback", err)

    def test_clauses_on_binary_body_is_clean_vaulterror(self):
        with temp_vault() as v:
            self._make_binary_template(Path(v))
            code, _out, err = run_cli("clauses", "nda/binary")
            self.assertEqual(code, 2)
            self.assertIn("not valid UTF-8", err)
            self.assertNotIn("Traceback", err)

    def test_read_text_utf8_helper(self):
        with temp_vault() as v:
            p = Path(v) / "b.pdf"
            p.write_bytes(b"\xff\xfe\x00")
            with self.assertRaises(tvc.VaultError):
                tvc._read_text_utf8(p)


class ImportMissingKeyTests(CliCase):
    def test_import_missing_url_raises_vaulterror(self):
        bad_reg = {"sources": [{"id": "broken", "category": "nda", "name": "x"}]}
        with temp_vault():
            with mock.patch.object(tvc, "load_sources_registry", return_value=bad_reg):
                code, _out, err = run_cli("import", "broken")
            self.assertEqual(code, 2)
            self.assertIn("broken", err)
            self.assertIn("url", err)
            self.assertNotIn("Traceback", err)

    def test_import_missing_category_raises_vaulterror(self):
        bad_reg = {"sources": [{"id": "broken2", "url": "https://x/y", "name": "x"}]}
        with temp_vault():
            with mock.patch.object(tvc, "load_sources_registry", return_value=bad_reg):
                code, _out, err = run_cli("import", "broken2")
            self.assertEqual(code, 2)
            self.assertIn("category", err)

    def test_unknown_source_with_keyless_entries_does_not_crash(self):
        # The "Available: ..." list must not KeyError on an entry missing 'id'.
        bad_reg = {"sources": [{"url": "https://x/y"}]}
        with temp_vault():
            with mock.patch.object(tvc, "load_sources_registry", return_value=bad_reg):
                code, _out, err = run_cli("import", "nope")
            self.assertEqual(code, 2)
            self.assertIn("Unknown source", err)
            self.assertNotIn("Traceback", err)


class GitAbsentInitTests(CliCase):
    def test_init_succeeds_without_git(self):
        def _no_git(_root, bare=False):  # type: ignore[no-untyped-def]
            raise FileNotFoundError("git")

        with temp_vault() as v:
            target = Path(v) / "subvault"
            with mock.patch.object(tvc, "_git_init", side_effect=_no_git):
                code, _out, err = run_cli("init", "--path", str(target))
            self.assertEqual(code, 0)
            self.assertTrue((target / tvc.VAULT_CONFIG_FILENAME).exists())
            self.assertIn("git not found", err)
            self.assertNotIn("Traceback", err)


class AtomicWriteTests(CliCase):
    def test_atomic_write_leaves_no_partial_on_crash(self):
        with temp_vault() as v:
            dest = Path(v) / "nda" / "x" / "v1.md"
            dest.parent.mkdir(parents=True)
            dest.write_text("ORIGINAL")

            # Force the rename to blow up; the destination must be untouched
            # and no stray temp file may remain.
            def _boom(_src, _dst):  # type: ignore[no-untyped-def]
                raise RuntimeError("crash mid-write")

            with mock.patch.object(tvc.os, "replace", side_effect=_boom):
                with self.assertRaises(RuntimeError):
                    tvc._secure_write_text(dest, "NEW CONTENT")

            self.assertEqual(dest.read_text(), "ORIGINAL")
            leftovers = [p for p in dest.parent.iterdir() if p.name.endswith(".tmp")]
            self.assertEqual(leftovers, [], f"stray temp files: {leftovers}")

    def test_secure_write_bytes_atomic_no_partial(self):
        with temp_vault() as v:
            dest = Path(v) / "blob.bin"
            dest.write_bytes(b"OLD")

            def _boom(_src, _dst):  # type: ignore[no-untyped-def]
                raise RuntimeError("crash")

            with mock.patch.object(tvc.os, "replace", side_effect=_boom):
                with self.assertRaises(RuntimeError):
                    tvc._secure_write_bytes(dest, b"NEWNEWNEW")
            self.assertEqual(dest.read_bytes(), b"OLD")
            self.assertFalse([p for p in Path(v).iterdir() if p.name.endswith(".tmp")])

    def test_save_meta_is_atomic_and_correct(self):
        with temp_vault() as v:
            add_template(Path(v), "nda", "a", "# A\n\n## 1. Purpose\nx\n")
            t = Path(v) / "nda" / "a"
            meta = tvc.load_meta(t)
            meta["summary"] = "updated"
            tvc.save_meta(t, meta)
            self.assertEqual(tvc.load_meta(t)["summary"], "updated")
            self.assertFalse([p for p in t.iterdir() if p.name.endswith(".tmp")])


class CatchAllTests(CliCase):
    def test_main_backstops_unexpected_exception(self):
        def _explode(_args):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

        with temp_vault():
            with mock.patch.object(tvc, "cmd_doctor", side_effect=_explode):
                code, _out, err = run_cli("doctor")
            self.assertEqual(code, 2)
            self.assertIn("unexpected", err)
            self.assertIn("RuntimeError", err)
            self.assertNotIn("Traceback", err)


class TopKClampTests(CliCase):
    def test_find_rejects_negative_top_k(self):
        with temp_vault() as v:
            add_template(Path(v), "nda", "a", "# A\n\n## 1. Purpose\nx\n")
            code, _out, err = run_cli("find", "purpose", "--top-k", "-1")
            self.assertEqual(code, 2)
            self.assertIn("top-k", err)


class TraversalStillRejectedTests(CliCase):
    """Sanity: the 0.5.1 path-containment fix still holds and writes nothing
    outside the vault root."""

    def test_upload_traversal_writes_nothing_outside_root(self):
        with temp_vault() as v:
            src = Path(v) / "src.md"
            src.write_text("# X\n\n## 1. Purpose\nhi\n")
            escape = Path(v).resolve().parent / "tvescape"
            code, _out, err = run_cli(
                "upload", str(src),
                "--category", "nda",
                "--name", "../../tvescape",
                "--summary", "s", "--non-interactive",
            )
            self.assertEqual(code, 2)
            self.assertIn("Invalid", err)
            self.assertFalse(escape.exists())


if __name__ == "__main__":
    unittest.main()
