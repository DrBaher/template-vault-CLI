"""upload command behavior."""

import json
import unittest
from pathlib import Path

from tests._helpers import CliCase, run_cli, temp_vault, tvc, SAMPLE_NDA_MUTUAL


class UploadTests(CliCase):
    def test_upload_writes_file_and_meta(self):
        with temp_vault() as v:
            src = v / "src.md"
            src.write_text(SAMPLE_NDA_MUTUAL)
            self.assertOk(run_cli(
                "upload", str(src),
                "--category", "nda", "--name", "house-mutual",
                "--summary", "the test NDA",
                "--non-interactive",
            ))
            t_dir = v / "nda" / "house-mutual"
            self.assertTrue((t_dir / "v1.md").exists())
            meta = json.loads((t_dir / "meta.json").read_text())
            self.assertEqual(meta["latest_version"], "v1")
            self.assertEqual(meta["category"], "nda")
            self.assertEqual(meta["versions"][0]["id"], "v1")
            self.assertEqual(meta["summary"], "the test NDA")

    def test_upload_auto_increments_version(self):
        with temp_vault() as v:
            src = v / "src.md"
            src.write_text(SAMPLE_NDA_MUTUAL)
            self.assertOk(run_cli(
                "upload", str(src), "--category", "nda", "--name", "x",
                "--summary", "s", "--non-interactive",
            ))
            self.assertOk(run_cli(
                "upload", str(src), "--category", "nda", "--name", "x",
                "--supersedes", "v1", "--summary", "s", "--non-interactive",
            ))
            meta = json.loads((v / "nda" / "x" / "meta.json").read_text())
            self.assertEqual(meta["latest_version"], "v2")
            ids = [ve["id"] for ve in meta["versions"]]
            self.assertEqual(ids, ["v1", "v2"])
            v1 = next(ve for ve in meta["versions"] if ve["id"] == "v1")
            self.assertEqual(v1.get("supersedes_by"), "v2")

    def test_upload_rejects_duplicate_version(self):
        with temp_vault() as v:
            src = v / "s.md"
            src.write_text(SAMPLE_NDA_MUTUAL)
            self.assertOk(run_cli("upload", str(src), "--category", "nda",
                                  "--name", "x", "--summary", "s",
                                  "--non-interactive"))
            code, _out, err = run_cli("upload", str(src), "--category", "nda",
                                      "--name", "x", "--version", "v1",
                                      "--summary", "s", "--non-interactive")
            self.assertNotEqual(code, 0)
            self.assertIn("already exists", err)

    def test_upload_requires_existing_file(self):
        with temp_vault():
            code, _out, err = run_cli("upload", "/no/such/file",
                                      "--category", "nda", "--name", "x",
                                      "--summary", "s", "--non-interactive")
            self.assertNotEqual(code, 0)
            self.assertIn("not found", err)

    def test_upload_records_jurisdiction_and_tags(self):
        with temp_vault() as v:
            src = v / "s.md"
            src.write_text(SAMPLE_NDA_MUTUAL)
            self.assertOk(run_cli(
                "upload", str(src), "--category", "nda", "--name", "x",
                "--summary", "s", "--non-interactive",
                "--tags", "house-style,short-form",
                "--jurisdiction", "California,Delaware",
                "--license", "MIT",
            ))
            meta = json.loads((v / "nda" / "x" / "meta.json").read_text())
            self.assertEqual(sorted(meta["jurisdiction"]), ["California", "Delaware"])
            self.assertIn("short-form", meta["tags"])
            self.assertEqual(meta["license"], "MIT")

    def test_upload_supersedes_updates_prior_pointer(self):
        with temp_vault() as v:
            src = v / "s.md"
            src.write_text(SAMPLE_NDA_MUTUAL)
            run_cli("upload", str(src), "--category", "nda", "--name", "y",
                    "--summary", "s", "--non-interactive")
            run_cli("upload", str(src), "--category", "nda", "--name", "y",
                    "--summary", "s2", "--supersedes", "v1", "--non-interactive")
            meta = json.loads((v / "nda" / "y" / "meta.json").read_text())
            v1 = next(ve for ve in meta["versions"] if ve["id"] == "v1")
            self.assertEqual(v1["supersedes_by"], "v2")
            v2 = next(ve for ve in meta["versions"] if ve["id"] == "v2")
            self.assertEqual(v2["supersedes"], "v1")

    def test_upload_outside_vault_errors(self):
        # Run from a freshly created dir without a .vault.json
        import os, tempfile
        with tempfile.TemporaryDirectory() as d:
            prev = os.getcwd()
            try:
                os.chdir(d)
                src = Path(d) / "s.md"
                src.write_text("body")
                code, _o, err = run_cli("upload", str(src),
                                        "--category", "nda", "--name", "x",
                                        "--summary", "s", "--non-interactive")
                self.assertNotEqual(code, 0)
                self.assertIn("vault", err.lower())
            finally:
                os.chdir(prev)


if __name__ == "__main__":
    unittest.main()
