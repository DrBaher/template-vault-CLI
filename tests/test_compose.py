"""compose command — fork + meta provenance."""

import json
import unittest

from tests._helpers import (
    CliCase, add_template, run_cli, temp_vault,
    SAMPLE_NDA_MUTUAL,
)


class ComposeTests(CliCase):
    def test_compose_creates_v1_with_lineage(self):
        with temp_vault() as v:
            add_template(v, "nda", "house-mutual", SAMPLE_NDA_MUTUAL,
                         tags=["house-style"], jurisdiction=["California"])
            self.assertOk(run_cli(
                "compose",
                "--base", "nda/house-mutual",
                "--as", "nda/house-mutual-startup",
            ))
            t = v / "nda" / "house-mutual-startup"
            self.assertTrue((t / "v1.md").exists())
            self.assertEqual(
                (t / "v1.md").read_text(),
                SAMPLE_NDA_MUTUAL,
            )
            meta = json.loads((t / "meta.json").read_text())
            self.assertEqual(meta["latest_version"], "v1")
            self.assertEqual(meta["derived_from"], "nda/house-mutual@v1")
            self.assertEqual(meta["forked_at_parent_version"], "v1")
            self.assertEqual(meta["clause_overrides"], [])
            # Inherits metadata
            self.assertIn("California", meta["jurisdiction"])
            self.assertIn("house-style", meta["tags"])

    def test_compose_fails_on_existing_target(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            add_template(v, "nda", "y", SAMPLE_NDA_MUTUAL)
            code, _out, err = run_cli(
                "compose", "--base", "nda/x", "--as", "nda/y",
            )
            self.assertNotEqual(code, 0)
            self.assertIn("already exists", err)

    def test_compose_fails_on_unknown_base(self):
        with temp_vault():
            code, _out, err = run_cli(
                "compose", "--base", "nda/missing", "--as", "nda/new",
            )
            self.assertNotEqual(code, 0)
            self.assertIn("not found", err)

    def test_compose_at_explicit_version(self):
        with temp_vault() as v:
            # Add a v1 then a v2
            add_template(v, "nda", "house", SAMPLE_NDA_MUTUAL, version="v1")
            t = v / "nda" / "house"
            (t / "v2.md").write_text(SAMPLE_NDA_MUTUAL.replace("Mutual", "Mutual v2"))
            meta = json.loads((t / "meta.json").read_text())
            meta["versions"].append({"id": "v2", "added": "2025-01-01",
                                     "supersedes": "v1", "changelog": "v2"})
            meta["latest_version"] = "v2"
            (t / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
            self.assertOk(run_cli(
                "compose", "--base", "nda/house@v1", "--as", "nda/house-fork",
            ))
            fork_meta = json.loads((v / "nda" / "house-fork" / "meta.json").read_text())
            self.assertEqual(fork_meta["forked_at_parent_version"], "v1")
            self.assertEqual(fork_meta["derived_from"], "nda/house@v1")


if __name__ == "__main__":
    unittest.main()
