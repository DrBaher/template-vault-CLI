"""swap command — clause replacement and failure modes."""

import json
import unittest

from tests._helpers import (
    CliCase, add_template, run_cli, temp_vault,
    SAMPLE_NDA_MUTUAL, SAMPLE_NDA_STARTUP_FRIENDLY,
)


class SwapTests(CliCase):
    def setUp(self):
        self._cm = temp_vault()
        self.vault = self._cm.__enter__()
        add_template(self.vault, "nda", "house-mutual", SAMPLE_NDA_MUTUAL)
        add_template(self.vault, "nda", "yc-friendly", SAMPLE_NDA_STARTUP_FRIENDLY)
        run_cli("compose", "--base", "nda/house-mutual",
                "--as", "nda/house-mutual-startup")

    def tearDown(self):
        self._cm.__exit__(None, None, None)

    def test_swap_replaces_only_named_clause(self):
        before = (self.vault / "nda" / "house-mutual-startup" / "v1.md").read_text()
        self.assertIn("two years after the last disclosure", before)
        self.assertOk(run_cli(
            "swap", "nda/house-mutual-startup",
            "--clause", "Term and Survival",
            "--from", "nda/yc-friendly",
        ))
        after = (self.vault / "nda" / "house-mutual-startup" / "v1.md").read_text()
        # New body inserted
        self.assertIn("one year from the Effective Date", after)
        # Old body for THAT clause is gone
        self.assertNotIn("two years after the last disclosure", after)
        # Other clauses untouched
        self.assertIn("Residual Knowledge", after)
        self.assertIn("unaided memory", after)
        self.assertIn("Each party shall protect", after)

    def test_swap_records_clause_override(self):
        run_cli("swap", "nda/house-mutual-startup",
                "--clause", "Term and Survival",
                "--from", "nda/yc-friendly")
        meta = json.loads(
            (self.vault / "nda" / "house-mutual-startup" / "meta.json").read_text()
        )
        overrides = meta["clause_overrides"]
        self.assertEqual(len(overrides), 1)
        self.assertEqual(overrides[0]["clause_title"], "Term and Survival")
        self.assertEqual(overrides[0]["source_template"], "nda/yc-friendly")
        self.assertEqual(overrides[0]["source_version"], "v1")
        self.assertIn("swapped_at", overrides[0])

    def test_swap_preserves_target_header(self):
        # Target uses "## 4. Term and Survival" — even though source uses
        # "## 4. Term and Survival", we want the target's anchor preserved.
        run_cli("swap", "nda/house-mutual-startup",
                "--clause", "Term and Survival",
                "--from", "nda/yc-friendly")
        after = (self.vault / "nda" / "house-mutual-startup" / "v1.md").read_text()
        self.assertIn("## 4. Term and Survival", after)

    def test_swap_fails_when_clause_missing_in_source(self):
        code, _out, err = run_cli(
            "swap", "nda/house-mutual-startup",
            "--clause", "Indemnification",
            "--from", "nda/yc-friendly",
        )
        self.assertNotEqual(code, 0)
        self.assertIn("not found", err.lower())
        # Lists available clauses
        self.assertIn("Available", err)
        self.assertIn("Term and Survival", err)

    def test_swap_fails_when_clause_missing_in_target(self):
        code, _out, err = run_cli(
            "swap", "nda/house-mutual-startup",
            "--clause", "Residual Knowledge",  # in target...
            "--from", "nda/yc-friendly",       # ...but not in source
        )
        self.assertNotEqual(code, 0)
        self.assertIn("not found", err.lower())

    def test_swap_fails_for_unknown_target(self):
        code, _out, err = run_cli(
            "swap", "nda/no-such",
            "--clause", "Purpose", "--from", "nda/yc-friendly",
        )
        self.assertNotEqual(code, 0)
        self.assertIn("not found", err.lower())

    def test_multiple_swaps_accumulate_in_overrides(self):
        run_cli("swap", "nda/house-mutual-startup",
                "--clause", "Term and Survival", "--from", "nda/yc-friendly")
        run_cli("swap", "nda/house-mutual-startup",
                "--clause", "Purpose", "--from", "nda/yc-friendly")
        meta = json.loads(
            (self.vault / "nda" / "house-mutual-startup" / "meta.json").read_text()
        )
        titles = [o["clause_title"] for o in meta["clause_overrides"]]
        self.assertEqual(titles, ["Term and Survival", "Purpose"])

    def test_swap_resolves_alias_to_canonical_clause(self):
        # Mark "Termination" as an alias of the source's "Term and Survival",
        # then `--clause Termination` should still find it.
        src_meta_path = self.vault / "nda" / "yc-friendly" / "meta.json"
        meta = json.loads(src_meta_path.read_text())
        meta["clause_aliases"] = {"Term and Survival": ["Termination"]}
        src_meta_path.write_text(json.dumps(meta, indent=2) + "\n")
        # Same alias on target so target lookup also resolves.
        tgt_meta_path = self.vault / "nda" / "house-mutual-startup" / "meta.json"
        tgt_meta = json.loads(tgt_meta_path.read_text())
        tgt_meta["clause_aliases"] = {"Term and Survival": ["Termination"]}
        tgt_meta_path.write_text(json.dumps(tgt_meta, indent=2) + "\n")

        code, _out, _err = run_cli(
            "swap", "nda/house-mutual-startup",
            "--clause", "Termination",
            "--from", "nda/yc-friendly",
        )
        self.assertEqual(code, 0)
        after = (self.vault / "nda" / "house-mutual-startup" / "v1.md").read_text()
        self.assertIn("one year from the Effective Date", after)


class InfoJsonTests(CliCase):
    def test_info_json_emits_clauses_and_metadata(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL,
                         jurisdiction=["California"], tags=["mutual"],
                         summary="house mutual NDA")
            code, out, _err = run_cli("info", "nda/x", "--json")
            self.assertEqual(code, 0)
            doc = json.loads(out)
            self.assertEqual(doc["ref"], "nda/x")
            self.assertEqual(doc["latest_version"], "v1")
            self.assertEqual(doc["jurisdiction"], ["California"])
            self.assertEqual(doc["tags"], ["mutual"])
            self.assertEqual(doc["summary"], "house mutual NDA")
            titles = [c["title"] for c in doc["clauses"]]
            self.assertIn("Term and Survival", titles)
            self.assertIn("Residual Knowledge", titles)


if __name__ == "__main__":
    unittest.main()
