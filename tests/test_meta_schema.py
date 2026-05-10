"""Schema and storage validation."""

import json
import unittest
from pathlib import Path

from tests._helpers import init_vault, temp_vault, tvc


class MetaSchemaTests(unittest.TestCase):
    def test_validate_meta_accepts_minimal(self):
        meta = {
            "name": "x",
            "category": "nda",
            "latest_version": "v1",
            "versions": [{"id": "v1"}],
        }
        self.assertEqual(tvc.validate_meta(meta), [])

    def test_validate_meta_flags_missing_required(self):
        errs = tvc.validate_meta({"name": "x"})
        self.assertTrue(any("category" in e for e in errs))
        self.assertTrue(any("latest_version" in e for e in errs))
        self.assertTrue(any("versions" in e for e in errs))

    def test_validate_meta_flags_dangling_latest(self):
        meta = {
            "name": "x",
            "category": "nda",
            "latest_version": "v9",
            "versions": [{"id": "v1"}],
        }
        errs = tvc.validate_meta(meta)
        self.assertTrue(any("latest_version" in e for e in errs))

    def test_validate_meta_flags_duplicate_versions(self):
        meta = {
            "name": "x",
            "category": "nda",
            "latest_version": "v1",
            "versions": [{"id": "v1"}, {"id": "v1"}],
        }
        errs = tvc.validate_meta(meta)
        self.assertTrue(any("duplicate" in e for e in errs))

    def test_validate_meta_versions_must_be_list(self):
        errs = tvc.validate_meta({"name": "x", "category": "nda",
                                  "latest_version": "v1", "versions": "v1"})
        self.assertTrue(any("list" in e for e in errs))

    def test_fill_defaults_doesnt_clobber(self):
        meta = {"name": "x", "category": "nda", "latest_version": "v1",
                "versions": [{"id": "v1"}], "tags": ["a"], "license": "MIT"}
        out = tvc.fill_meta_defaults(meta)
        self.assertEqual(out["tags"], ["a"])
        self.assertEqual(out["license"], "MIT")
        self.assertEqual(out["clause_overrides"], [])
        self.assertIsNone(out["derived_from"])

    def test_validate_vault_config_accepts_canonical(self):
        cfg = {"schema_version": tvc.SCHEMA_VERSION, "sources": []}
        self.assertEqual(tvc.validate_vault_config(cfg), [])

    def test_validate_vault_config_rejects_wrong_schema(self):
        cfg = {"schema_version": 999}
        errs = tvc.validate_vault_config(cfg)
        self.assertTrue(any("schema_version" in e for e in errs))

    def test_validate_vault_config_rejects_non_object(self):
        errs = tvc.validate_vault_config("hello")  # type: ignore[arg-type]
        self.assertTrue(any("object" in e for e in errs))

    def test_validate_vault_config_rejects_bad_sources(self):
        cfg = {"schema_version": tvc.SCHEMA_VERSION, "sources": "nope"}
        errs = tvc.validate_vault_config(cfg)
        self.assertTrue(any("sources" in e for e in errs))


class VaultDiscoveryTests(unittest.TestCase):
    def test_find_vault_root_walks_upward(self):
        with temp_vault() as v:
            sub = v / "nested" / "deeper"
            sub.mkdir(parents=True)
            self.assertEqual(tvc.find_vault_root(sub), v)

    def test_find_vault_root_raises_when_missing(self):
        with self.assertRaises(tvc.NotFoundError):
            tvc.find_vault_root(Path("/"))

    def test_read_vault_config_rejects_malformed_json(self):
        with temp_vault() as v:
            (v / tvc.VAULT_CONFIG_FILENAME).write_text("not json {")
            with self.assertRaises(tvc.VaultError):
                tvc.read_vault_config(v)


class ParseRefTests(unittest.TestCase):
    def test_parses_basic(self):
        self.assertEqual(tvc.parse_ref("nda/foo"), ("nda", "foo", None))

    def test_parses_with_version(self):
        self.assertEqual(tvc.parse_ref("nda/foo@v3"), ("nda", "foo", "v3"))

    def test_rejects_no_slash(self):
        with self.assertRaises(tvc.VaultError):
            tvc.parse_ref("foo")

    def test_rejects_empty_version(self):
        with self.assertRaises(tvc.VaultError):
            tvc.parse_ref("nda/foo@")


if __name__ == "__main__":
    unittest.main()
