"""doctor command — vault integrity checks."""

import json
import os
import unittest
from pathlib import Path

from tests._helpers import (
    CliCase, add_template, run_cli, temp_vault, tvc,
    SAMPLE_NDA_MUTUAL,
)


class DoctorTests(CliCase):
    def test_clean_vault_reports_ok(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            code, out, _err = run_cli("doctor")
            self.assertEqual(code, 0)
            self.assertIn("OK", out)

    def test_flags_missing_meta(self):
        with temp_vault() as v:
            (v / "nda" / "broken").mkdir(parents=True)
            (v / "nda" / "broken" / "v1.md").write_text("# x")
            code, out, _err = run_cli("doctor")
            self.assertNotEqual(code, 0)
            self.assertIn("missing meta.json", out)

    def test_flags_dangling_latest(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            mp = v / "nda" / "x" / "meta.json"
            meta = json.loads(mp.read_text())
            meta["latest_version"] = "v9"
            mp.write_text(json.dumps(meta, indent=2) + "\n")
            code, out, _err = run_cli("doctor")
            self.assertNotEqual(code, 0)
            self.assertIn("latest_version", out)

    def test_flags_version_gaps(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            t = v / "nda" / "x"
            (t / "v3.md").write_text("# v3")
            meta = json.loads((t / "meta.json").read_text())
            meta["versions"].append({"id": "v3", "added": "2025-01-01",
                                     "supersedes": "v1", "changelog": "x"})
            meta["latest_version"] = "v3"
            (t / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
            code, out, _err = run_cli("doctor")
            self.assertNotEqual(code, 0)
            self.assertIn("gap", out.lower())

    def test_flags_unknown_explicit_anchor(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            mp = v / "nda" / "x" / "meta.json"
            meta = json.loads(mp.read_text())
            meta["clauses"] = [{"title": "Bogus", "anchor": "## 999. Missing"}]
            mp.write_text(json.dumps(meta, indent=2) + "\n")
            code, out, _err = run_cli("doctor")
            self.assertNotEqual(code, 0)
            self.assertIn("anchor", out.lower())

    def test_warns_on_empty_summary(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            # Scrub summary so the warning fires.
            mp = v / "nda" / "x" / "meta.json"
            meta = json.loads(mp.read_text())
            meta["summary"] = ""
            mp.write_text(json.dumps(meta, indent=2) + "\n")
            code, out, _err = run_cli("doctor")
            self.assertEqual(code, 0)  # warnings don't fail by default
            self.assertIn("Quality warnings", out)
            self.assertIn("empty summary", out)

    def test_warns_on_unrecorded_sha256(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            code, out, _err = run_cli("doctor")
            self.assertEqual(code, 0)
            # Newly-added templates have no recorded sha256 -> warning.
            self.assertIn("without recorded sha256", out)
            self.assertIn("verify --update-hashes", out)

    def test_warns_on_never_used_template(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            code, out, _err = run_cli("doctor")
            self.assertEqual(code, 0)
            self.assertIn("never used", out)

    def test_warns_on_no_clauses_detected(self):
        with temp_vault() as v:
            # Template with no H2 / fallback-detectable headings.
            add_template(v, "nda", "flat", "Just plain prose. No headings.\n")
            code, out, _err = run_cli("doctor")
            self.assertEqual(code, 0)
            self.assertIn("no clauses detected", out.lower())

    def test_quiet_warnings_suppresses_them(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            code, out, _err = run_cli("doctor", "--quiet-warnings")
            self.assertEqual(code, 0)
            self.assertNotIn("Quality warnings", out)
            self.assertNotIn("never used", out)

    def test_strict_treats_warnings_as_failures(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            code, _out, _err = run_cli("doctor", "--strict")
            # Warnings DO exist (empty summary etc.), strict makes them fail.
            self.assertNotEqual(code, 0)

    def test_flags_dangling_clause_alias_key(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            mp = v / "nda" / "x" / "meta.json"
            meta = json.loads(mp.read_text())
            # "Indemnification" isn't a real clause in SAMPLE_NDA_MUTUAL.
            meta["clause_aliases"] = {"Indemnification": ["Indemnity"]}
            mp.write_text(json.dumps(meta, indent=2) + "\n")
            code, out, _err = run_cli("doctor")
            self.assertNotEqual(code, 0)
            self.assertIn("clause_aliases", out)
            self.assertIn("Indemnification", out)


class FirstRunHintTests(CliCase):
    def test_bare_invocation_prints_hint(self):
        code, out, _err = run_cli()
        self.assertEqual(code, 0)
        self.assertIn("First-run", out)
        self.assertIn("template-vault init", out)

    def test_version_flag(self):
        code, out, _err = run_cli("--version")
        self.assertEqual(code, 0)
        self.assertIn(tvc.__version__, out)


if __name__ == "__main__":
    unittest.main()
