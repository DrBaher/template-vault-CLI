"""template-vault stats: vault dashboard command."""

import json
import unittest

from tests._helpers import (
    CliCase, add_template, run_cli, temp_vault,
    SAMPLE_NDA_MUTUAL, SAMPLE_NDA_STARTUP_FRIENDLY, SAMPLE_LICENSING,
)


class StatsTests(CliCase):
    def test_empty_vault_runs_clean(self):
        with temp_vault():
            code, out, _err = run_cli("stats")
            self.assertEqual(code, 0)
            self.assertIn("Vault:", out)
            self.assertIn("Templates:     0", out)

    def test_populated_vault_shows_category_breakdown(self):
        with temp_vault() as v:
            add_template(v, "nda", "house", SAMPLE_NDA_MUTUAL, tags=["mutual"],
                         summary="house mutual NDA")
            add_template(v, "nda", "yc", SAMPLE_NDA_STARTUP_FRIENDLY,
                         summary="yc-flavor NDA")
            add_template(v, "licensing", "saas", SAMPLE_LICENSING)
            # Scrub one summary so the coverage line shows 2/3.
            mp = v / "licensing" / "saas" / "meta.json"
            meta = json.loads(mp.read_text())
            meta["summary"] = ""
            mp.write_text(json.dumps(meta, indent=2) + "\n")

            code, out, _err = run_cli("stats")
            self.assertEqual(code, 0)
            self.assertIn("Templates:     3", out)
            self.assertIn("nda: 2", out)
            self.assertIn("licensing: 1", out)
            self.assertIn("Coverage:", out)
            self.assertIn("2/3", out)  # 2 of 3 templates have summaries

    def test_json_payload_shape(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL, summary="s")
            code, out, _err = run_cli("stats", "--json")
            self.assertEqual(code, 0)
            doc = json.loads(out)
            self.assertEqual(doc["templates"], 1)
            self.assertEqual(doc["categories"], {"nda": 1})
            self.assertIn("coverage", doc)
            self.assertEqual(doc["coverage"]["with_summary"], [1, 1])
            self.assertEqual(doc["coverage"]["with_tags"], [0, 1])

    def test_stats_counts_compositions_separately(self):
        with temp_vault() as v:
            add_template(v, "nda", "house", SAMPLE_NDA_MUTUAL)
            run_cli("compose", "--base", "nda/house", "--as", "nda/derived")
            code, out, _err = run_cli("stats")
            self.assertEqual(code, 0)
            self.assertIn("Templates:     2", out)
            self.assertIn("Compositions:", out)
            self.assertIn("1", out)

    def test_stats_reports_last_activity(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            code, out, _err = run_cli("stats")
            self.assertEqual(code, 0)
            self.assertIn("Last activity:", out)
            self.assertIn("nda/x@v1", out)


if __name__ == "__main__":
    unittest.main()
