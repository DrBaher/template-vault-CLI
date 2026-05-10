"""list / find / get / info / diff."""

import unittest

from tests._helpers import (
    CliCase, add_template, run_cli, temp_vault,
    SAMPLE_NDA_MUTUAL, SAMPLE_NDA_STARTUP_FRIENDLY, SAMPLE_LICENSING,
)


class ListFilterTests(CliCase):
    def setUp(self):
        self._cm = temp_vault()
        self.vault = self._cm.__enter__()
        add_template(self.vault, "nda", "house-mutual", SAMPLE_NDA_MUTUAL,
                     jurisdiction=["California"], tags=["house-style"])
        add_template(self.vault, "nda", "yc-startup", SAMPLE_NDA_STARTUP_FRIENDLY,
                     jurisdiction=["Delaware"], tags=["yc"])
        add_template(self.vault, "licensing", "saas-enterprise", SAMPLE_LICENSING,
                     tags=["saas"])

    def tearDown(self):
        self._cm.__exit__(None, None, None)

    def test_list_all(self):
        code, out, _err = run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("nda/house-mutual", out)
        self.assertIn("nda/yc-startup", out)
        self.assertIn("licensing/saas-enterprise", out)

    def test_list_filter_category(self):
        code, out, _err = run_cli("list", "--category", "nda")
        self.assertEqual(code, 0)
        self.assertIn("nda/house-mutual", out)
        self.assertNotIn("licensing/saas-enterprise", out)

    def test_list_filter_tag(self):
        code, out, _err = run_cli("list", "--tag", "yc")
        self.assertEqual(code, 0)
        self.assertIn("yc-startup", out)
        self.assertNotIn("house-mutual", out)

    def test_list_filter_jurisdiction(self):
        code, out, _err = run_cli("list", "--jurisdiction", "California")
        self.assertEqual(code, 0)
        self.assertIn("house-mutual", out)
        self.assertNotIn("yc-startup", out)


class FindTests(CliCase):
    def test_find_keyword_substring(self):
        with temp_vault() as v:
            add_template(v, "nda", "house-mutual", SAMPLE_NDA_MUTUAL,
                         summary="standard mutual NDA for vendor diligence")
            add_template(v, "licensing", "saas", SAMPLE_LICENSING,
                         summary="enterprise SaaS license, on-prem optional")
            code, out, _err = run_cli("find", "vendor")
            self.assertEqual(code, 0)
            self.assertIn("house-mutual", out)
            self.assertNotIn("licensing/saas", out)

    def test_find_returns_no_matches_message(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL, summary="alpha")
            code, out, _err = run_cli("find", "zzznoresult")
            self.assertEqual(code, 0)
            self.assertIn("no matches", out)


class GetTests(CliCase):
    def test_get_at_latest(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            code, out, _err = run_cli("get", "nda/x")
            self.assertEqual(code, 0)
            self.assertIn("Mutual NDA", out)

    def test_get_at_explicit_version(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            code, out, _err = run_cli("get", "nda/x@v1")
            self.assertEqual(code, 0)
            self.assertIn("Mutual NDA", out)

    def test_get_unknown_template_errors(self):
        with temp_vault():
            code, _out, err = run_cli("get", "nda/nope")
            self.assertNotEqual(code, 0)
            self.assertIn("No such template", err)

    def test_get_unknown_version_errors(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            code, _out, err = run_cli("get", "nda/x@v999")
            self.assertNotEqual(code, 0)
            self.assertIn("not found", err.lower())

    def test_get_path_only(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            code, out, _err = run_cli("get", "nda/x", "--path-only")
            self.assertEqual(code, 0)
            self.assertIn("nda/x/v1.md", out.replace("\\", "/"))

    def test_get_increments_use_count(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            run_cli("get", "nda/x")
            run_cli("get", "nda/x")
            import json
            meta = json.loads((v / "nda" / "x" / "meta.json").read_text())
            self.assertEqual(meta["use_count"], 2)
            self.assertIsNotNone(meta["last_used"])


class InfoTests(CliCase):
    def test_info_shows_summary_and_clauses(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL,
                         summary="hello", tags=["a"], jurisdiction=["NY"])
            code, out, _err = run_cli("info", "nda/x")
            self.assertEqual(code, 0)
            self.assertIn("hello", out)
            self.assertIn("NY", out)
            self.assertIn("a", out)


class DiffTests(CliCase):
    def test_diff_shows_changes(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", "## A\nold body\n", version="v1")
            # Add a v2 manually
            t = v / "nda" / "x"
            (t / "v2.md").write_text("## A\nnew body\n")
            import json
            meta = json.loads((t / "meta.json").read_text())
            meta["versions"].append({"id": "v2", "added": "2025-01-01",
                                     "supersedes": "v1", "changelog": "x"})
            meta["latest_version"] = "v2"
            (t / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
            code, out, _err = run_cli("diff", "nda/x", "v1", "v2")
            self.assertEqual(code, 0)
            self.assertIn("-old body", out)
            self.assertIn("+new body", out)


if __name__ == "__main__":
    unittest.main()
