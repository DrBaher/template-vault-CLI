"""Security regressions: path containment and URL-scheme validation.

These guard the two filesystem/network trust boundaries:
  * category/name components must stay inside the vault root (no `../../`),
  * urllib is only handed http/https (no file:// arbitrary read, no plain
    http to a remote host that would leak an API key).
"""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from tests._helpers import (
    CliCase, run_cli, temp_vault, tvc, add_template, SAMPLE_NDA_MUTUAL,
)


class PathContainmentTests(unittest.TestCase):
    def test_validate_rejects_traversal_components(self):
        for bad in ("..", ".", "../etc", "a/b", "a\\b", "/etc", "", "x\x00y"):
            with self.assertRaises(tvc.VaultError, msg=f"{bad!r} should be rejected"):
                tvc._validate_path_component(bad, "name")

    def test_validate_allows_ordinary_names(self):
        for ok in ("nda", "house-mutual", "common-paper", "v1_0", "a.b", "X9"):
            self.assertEqual(tvc._validate_path_component(ok, "name"), ok)

    def test_template_dir_blocks_escape(self):
        root = Path("/tmp/vault-root")
        with self.assertRaises(tvc.VaultError):
            tvc.template_dir(root, "..", "x")
        with self.assertRaises(tvc.VaultError):
            tvc.template_dir(root, "nda", "../../etc/passwd")

    def test_template_dir_ok_for_valid(self):
        root = Path("/tmp/vault-root")
        self.assertEqual(
            tvc.template_dir(root, "nda", "house-mutual"),
            root / "nda" / "house-mutual",
        )


class TraversalViaCliTests(CliCase):
    def test_compose_as_cannot_escape_vault(self):
        # The classic ../../etc/passwd attack, routed through `compose --as`.
        with temp_vault() as v:
            add_template(v, "nda", "house", SAMPLE_NDA_MUTUAL)
            code, _out, err = run_cli(
                "compose", "--base", "nda/house", "--as", "nda/../../etc/passwd",
            )
            self.assertNotEqual(code, 0)
            self.assertIn("Invalid", err)
            # Nothing was written outside the vault.
            self.assertFalse((v.parent / "etc").exists())

    def test_upload_category_cannot_escape_vault(self):
        with temp_vault() as v:
            src = v / "src.md"
            src.write_text(SAMPLE_NDA_MUTUAL)
            code, _out, err = run_cli(
                "upload", str(src),
                "--category", "../../../tmp", "--name", "evil",
                "--summary", "s", "--non-interactive",
            )
            self.assertNotEqual(code, 0)
            self.assertIn("Invalid", err)


class UrlSchemeTests(unittest.TestCase):
    def test_require_safe_url_blocks_dangerous_schemes(self):
        for bad in ("file:///etc/passwd", "gopher://x/", "ftp://h/f", "data:,hi"):
            with self.assertRaises(tvc.VaultError):
                tvc._require_safe_url(bad, context="source", allow_remote_http=True)

    def test_require_safe_url_allows_https(self):
        url = "https://example.com/x"
        self.assertEqual(
            tvc._require_safe_url(url, context="source", allow_remote_http=True), url)

    def test_llm_base_url_blocks_remote_plain_http(self):
        # An API key would ride this request; plain http to a remote host is refused.
        with self.assertRaises(tvc.VaultError):
            tvc._require_safe_url(
                "http://evil.example/v1", context="LLM base_url",
                allow_remote_http=False)

    def test_llm_base_url_allows_localhost_http(self):
        # Local LLMs (Ollama/LM Studio) legitimately use http://localhost.
        for ok in ("http://localhost:11434/v1", "http://127.0.0.1:8000/v1"):
            self.assertEqual(
                tvc._require_safe_url(ok, context="LLM base_url",
                                      allow_remote_http=False), ok)

    def test_fetch_url_refuses_file_scheme(self):
        # Must reject before urlopen — i.e. it never reads the local file.
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("TOP SECRET")
            secret = f.name
        with self.assertRaises(tvc.VaultError):
            tvc._fetch_url(f"file://{secret}")


class ImportRejectsFileUrlTests(CliCase):
    def test_import_with_file_url_registry_is_refused(self):
        with temp_vault() as v:
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
                f.write("TOP SECRET")
                secret = f.name
            reg = v / "evil-sources.json"
            reg.write_text(json.dumps({
                "schema_version": tvc.SCHEMA_VERSION,
                "sources": [{
                    "id": "evil", "category": "nda", "name": "evil",
                    "url": f"file://{secret}", "license": "x", "sha256": None,
                }],
            }))
            code, _out, err = run_cli("import", "evil", "--sources", str(reg))
            self.assertNotEqual(code, 0)
            self.assertNotIn("TOP SECRET", err)
            self.assertFalse((v / "nda" / "evil").exists())


@unittest.skipUnless(os.name == "posix", "POSIX permission semantics only")
class PermissionTests(CliCase):
    def _mode(self, p: Path) -> int:
        return stat.S_IMODE(p.stat().st_mode)

    def test_init_creates_owner_only_vault_dir(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d) / "vault"  # does not exist yet -> we create it
            self.assertOk(run_cli("init", "--path", str(vault)))
            self.assertEqual(self._mode(vault), 0o700)
            self.assertEqual(self._mode(vault / tvc.VAULT_CONFIG_FILENAME), 0o600)

    def test_upload_writes_owner_only_files(self):
        with temp_vault() as v:
            src = v / "src.md"
            src.write_text(SAMPLE_NDA_MUTUAL)
            self.assertOk(run_cli(
                "upload", str(src), "--category", "nda", "--name", "house",
                "--summary", "s", "--non-interactive",
            ))
            t_dir = v / "nda" / "house"
            self.assertEqual(self._mode(t_dir), 0o700)
            self.assertEqual(self._mode(t_dir / "meta.json"), 0o600)
            self.assertEqual(self._mode(t_dir / "v1.md"), 0o600)


if __name__ == "__main__":
    unittest.main()
