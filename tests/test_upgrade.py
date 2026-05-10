"""upgrade command — parent-diff merge, accept-all, locally swapped clauses."""

import json
import unittest

from tests._helpers import (
    CliCase, add_template, run_cli, temp_vault, tvc,
    SAMPLE_NDA_MUTUAL, SAMPLE_NDA_STARTUP_FRIENDLY,
)


PARENT_V2_BODY = SAMPLE_NDA_MUTUAL.replace(
    "two years after the last disclosure",
    "THREE years after the last disclosure",
).replace(
    "Each party shall protect the other's Confidential Information.",
    "Each party shall protect the other's Confidential Information using "
    "industry-standard care.",
)


def _add_v2_to_parent(vault, cat, name, body, vid="v2"):
    """Append a v2 to an existing template."""
    t = vault / cat / name
    (t / f"{vid}.md").write_text(body)
    meta = json.loads((t / "meta.json").read_text())
    for v in meta["versions"]:
        if v["id"] == meta["latest_version"]:
            v["supersedes_by"] = vid
    meta["versions"].append({
        "id": vid, "added": "2025-02-02",
        "supersedes": meta["latest_version"], "changelog": "tightened",
    })
    meta["latest_version"] = vid
    (t / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")


class UpgradeTests(CliCase):
    def setUp(self):
        self._cm = temp_vault()
        self.vault = self._cm.__enter__()
        add_template(self.vault, "nda", "house-mutual", SAMPLE_NDA_MUTUAL)
        add_template(self.vault, "nda", "yc-friendly", SAMPLE_NDA_STARTUP_FRIENDLY)
        run_cli("compose",
                "--base", "nda/house-mutual",
                "--as", "nda/house-mutual-startup")

    def tearDown(self):
        self._cm.__exit__(None, None, None)

    def test_upgrade_no_op_when_parent_unchanged(self):
        code, out, _err = run_cli("upgrade", "nda/house-mutual-startup")
        self.assertEqual(code, 0)
        self.assertIn("Up to date", out)

    def test_upgrade_accept_all_pulls_changes(self):
        _add_v2_to_parent(self.vault, "nda", "house-mutual", PARENT_V2_BODY)
        code, out, _err = run_cli(
            "upgrade", "nda/house-mutual-startup", "--accept-all")
        self.assertEqual(code, 0)
        derived = self.vault / "nda" / "house-mutual-startup"
        meta = json.loads((derived / "meta.json").read_text())
        self.assertEqual(meta["latest_version"], "v2")
        self.assertEqual(meta["forked_at_parent_version"], "v2")
        self.assertTrue((derived / "v2.md").exists())
        new_body = (derived / "v2.md").read_text()
        self.assertIn("THREE years after the last disclosure", new_body)
        self.assertIn("industry-standard care", new_body)

    def test_upgrade_skips_locally_swapped_clauses(self):
        # Swap the "Term and Survival" clause from yc-friendly into derived
        run_cli("swap", "nda/house-mutual-startup",
                "--clause", "Term and Survival",
                "--from", "nda/yc-friendly")
        # Now the parent gets a new "Term and Survival" upstream
        _add_v2_to_parent(self.vault, "nda", "house-mutual", PARENT_V2_BODY)
        code, out, _err = run_cli(
            "upgrade", "nda/house-mutual-startup", "--accept-all")
        self.assertEqual(code, 0)
        # Locally-swapped clause stays as the YC body (one year), not parent's THREE years
        new_body = (self.vault / "nda" / "house-mutual-startup" / "v2.md").read_text()
        self.assertIn("one year from the Effective Date", new_body)
        self.assertNotIn("THREE years after the last disclosure", new_body)
        # But other clauses do get the upstream improvement
        self.assertIn("industry-standard care", new_body)

    def test_upgrade_errors_for_non_derived_template(self):
        code, _out, err = run_cli("upgrade", "nda/house-mutual")
        self.assertNotEqual(code, 0)
        self.assertIn("derived_from", err)


if __name__ == "__main__":
    unittest.main()
