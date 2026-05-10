"""import command — mocked urllib, hash verification, registry handling."""

import hashlib
import io
import json
import unittest
from unittest import mock

from tests._helpers import CliCase, run_cli, temp_vault, tvc


SAMPLE_BODY = b"# Common Paper Mutual NDA (test)\n\n## 1. Purpose\nshort\n"


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body
    def read(self):
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False


def _patched_registry(extra=None):
    """Return a registry dict with the bundled sources but tweakable for tests."""
    base = tvc.load_sources_registry()
    if extra:
        base["sources"] = extra + base["sources"]
    return base


class ImportTests(CliCase):
    def test_unknown_source_errors(self):
        with temp_vault():
            code, _out, err = run_cli("import", "no-such-source")
            self.assertNotEqual(code, 0)
            self.assertIn("Unknown source", err)

    def test_import_writes_template_and_meta(self):
        with temp_vault() as v:
            with mock.patch.object(tvc, "_fetch_url", return_value=SAMPLE_BODY):
                code, _out, _err = run_cli("import", "common-paper-mutual-nda")
                self.assertEqual(code, 0)
            t = v / "nda" / "common-paper-mutual"
            self.assertTrue(t.exists())
            files = list(t.glob("v1*"))
            self.assertEqual(len(files), 1)
            meta = json.loads((t / "meta.json").read_text())
            self.assertEqual(meta["latest_version"], "v1")
            self.assertEqual(meta["license"], "CC BY 4.0")
            self.assertIn("commonpaper", meta["source"])
            self.assertIn("common-paper", meta["tags"])

    def test_import_records_observed_sha256(self):
        with temp_vault() as v:
            with mock.patch.object(tvc, "_fetch_url", return_value=SAMPLE_BODY):
                run_cli("import", "common-paper-mutual-nda")
            meta = json.loads((v / "nda" / "common-paper-mutual" / "meta.json").read_text())
            ver = meta["versions"][0]
            self.assertEqual(ver["sha256"], hashlib.sha256(SAMPLE_BODY).hexdigest())

    def test_import_hash_mismatch_aborts(self):
        # Patch the registry to require a specific hash that won't match
        with temp_vault():
            registry = tvc.load_sources_registry()
            for s in registry["sources"]:
                if s["id"] == "common-paper-mutual-nda":
                    s["sha256"] = "0" * 64
            with mock.patch.object(tvc, "load_sources_registry", return_value=registry), \
                 mock.patch.object(tvc, "_fetch_url", return_value=SAMPLE_BODY):
                code, _out, err = run_cli("import", "common-paper-mutual-nda")
                self.assertNotEqual(code, 0)
                self.assertIn("mismatch", err.lower())

    def test_import_no_verify_bypasses_mismatch(self):
        with temp_vault() as v:
            registry = tvc.load_sources_registry()
            for s in registry["sources"]:
                if s["id"] == "common-paper-mutual-nda":
                    s["sha256"] = "0" * 64
            with mock.patch.object(tvc, "load_sources_registry", return_value=registry), \
                 mock.patch.object(tvc, "_fetch_url", return_value=SAMPLE_BODY):
                code, _out, _err = run_cli(
                    "import", "common-paper-mutual-nda", "--no-verify")
                self.assertEqual(code, 0)
            self.assertTrue((v / "nda" / "common-paper-mutual" / "meta.json").exists())

    def test_import_pin_hash_writes_to_vault_config(self):
        with temp_vault() as v:
            with mock.patch.object(tvc, "_fetch_url", return_value=SAMPLE_BODY):
                code, _out, _err = run_cli(
                    "import", "common-paper-mutual-nda", "--pin-hash")
                self.assertEqual(code, 0)
            cfg = json.loads((v / tvc.VAULT_CONFIG_FILENAME).read_text())
            pinned = cfg.get("pinned_source_hashes", {})
            self.assertEqual(
                pinned.get("common-paper-mutual-nda"),
                hashlib.sha256(SAMPLE_BODY).hexdigest(),
            )


class SourcesListTests(CliCase):
    def test_sources_lists_bundled_ids(self):
        with temp_vault():
            code, out, _err = run_cli("sources")
            self.assertEqual(code, 0)
            self.assertIn("common-paper-mutual-nda", out)
            self.assertIn("CC BY 4.0", out)


CUSTOM_REGISTRY = {
    "schema_version": 1,
    "sources": [{
        "id": "internal-vendor-nda",
        "category": "nda",
        "name": "internal-vendor-nda",
        "url": "https://internal.example.test/templates/vendor-nda.md",
        "license": "internal-use-only",
        "attribution": "Internal legal team",
        "sha256": None,
        "summary": "Vendor NDA, internal use only",
        "tags": ["internal", "vendor"],
    }],
}


class CustomRegistryTests(CliCase):
    def test_sources_flag_overrides_bundled(self):
        with temp_vault() as v:
            reg = v / "internal-sources.json"
            reg.write_text(json.dumps(CUSTOM_REGISTRY))
            code, out, _err = run_cli("sources", "--sources", str(reg))
            self.assertEqual(code, 0)
            self.assertIn("Custom sources", out)
            self.assertIn("internal-vendor-nda", out)
            self.assertNotIn("common-paper-mutual-nda", out)

    def test_sources_env_var_overrides_bundled(self):
        import os
        with temp_vault() as v:
            reg = v / "internal-sources.json"
            reg.write_text(json.dumps(CUSTOM_REGISTRY))
            os.environ[tvc.SOURCES_ENV] = str(reg)
            try:
                code, out, _err = run_cli("sources")
                self.assertEqual(code, 0)
                self.assertIn("internal-vendor-nda", out)
            finally:
                del os.environ[tvc.SOURCES_ENV]

    def test_cli_flag_wins_over_env_var(self):
        import os
        with temp_vault() as v:
            env_reg = v / "env-sources.json"
            env_reg.write_text(json.dumps({
                "schema_version": 1, "sources": [{
                    "id": "env-only", "category": "nda", "name": "env",
                    "url": "x", "license": "x", "sha256": None,
                    "summary": "", "tags": [],
                }]}))
            flag_reg = v / "flag-sources.json"
            flag_reg.write_text(json.dumps(CUSTOM_REGISTRY))
            os.environ[tvc.SOURCES_ENV] = str(env_reg)
            try:
                code, out, _err = run_cli("sources", "--sources", str(flag_reg))
                self.assertEqual(code, 0)
                self.assertIn("internal-vendor-nda", out)
                self.assertNotIn("env-only", out)
            finally:
                del os.environ[tvc.SOURCES_ENV]

    def test_import_uses_custom_registry(self):
        with temp_vault() as v:
            reg = v / "internal-sources.json"
            reg.write_text(json.dumps(CUSTOM_REGISTRY))
            with mock.patch.object(tvc, "_fetch_url", return_value=SAMPLE_BODY):
                code, _out, _err = run_cli(
                    "import", "internal-vendor-nda", "--sources", str(reg))
                self.assertEqual(code, 0)
            t = v / "nda" / "internal-vendor-nda"
            meta = json.loads((t / "meta.json").read_text())
            self.assertEqual(meta["license"], "internal-use-only")
            self.assertEqual(meta["source"], "https://internal.example.test/templates/vendor-nda.md")

    def test_missing_custom_registry_errors(self):
        with temp_vault():
            code, _out, err = run_cli(
                "sources", "--sources", "/no/such/file.json")
            self.assertNotEqual(code, 0)
            self.assertIn("not found", err.lower())

    def test_malformed_custom_registry_errors(self):
        with temp_vault() as v:
            reg = v / "broken.json"
            reg.write_text("{ not valid json")
            code, _out, err = run_cli("sources", "--sources", str(reg))
            self.assertNotEqual(code, 0)
            self.assertIn("malformed", err.lower())


if __name__ == "__main__":
    unittest.main()
