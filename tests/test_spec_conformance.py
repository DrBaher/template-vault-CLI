"""Lock the docs/spec/*.schema.json files against the actual JSON output
of the corresponding commands.

We deliberately don't add `jsonschema` as a dependency — that'd violate
the stdlib-only posture. Instead, we spot-check: every `required` field
declared in the schema must appear in the real command output. Catches
the most common drift mode (code adds/removes a field; schema not
updated, or vice versa). Doesn't validate types or constraints — for
that, a downstream tool can run a real validator against these same
schema files (which is what INTEROP.md invites them to do).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests._helpers import (
    CliCase, add_template, run_cli, temp_vault,
    SAMPLE_NDA_MUTUAL, SAMPLE_NDA_STARTUP_FRIENDLY,
)

_SPEC_DIR = Path(__file__).resolve().parent.parent / "docs" / "spec"


def _required_fields(schema_path: Path) -> list:
    return json.loads(schema_path.read_text())["required"]


class SchemaShipsCoreFieldsTests(CliCase):
    """For each --json command, confirm the live output includes every
    'required' field its schema declares. Doesn't enforce types -- a real
    JSON-Schema validator (in a downstream tool) does that. This is the
    cheap drift alarm."""

    def test_info_json_includes_required_fields(self):
        required = _required_fields(_SPEC_DIR / "info-json.schema.json")
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL, summary="s")
            code, out, _err = run_cli("info", "nda/x", "--json")
            self.assertEqual(code, 0)
            payload = json.loads(out)
        for f in required:
            self.assertIn(f, payload,
                f"info --json output missing required field '{f}'. "
                f"Update either docs/spec/info-json.schema.json or "
                f"cmd_info()'s payload construction.",
            )

    def test_find_json_includes_required_fields(self):
        required = _required_fields(_SPEC_DIR / "find-json.schema.json")
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL, summary="house")
            code, out, _err = run_cli("find", "house", "--json")
            self.assertEqual(code, 0)
            payload = json.loads(out)
        for f in required:
            self.assertIn(f, payload, f"find --json missing '{f}'")

    def test_history_json_includes_required_fields(self):
        required = _required_fields(_SPEC_DIR / "history-json.schema.json")
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL, summary="s")
            code, out, _err = run_cli("history", "nda/x", "--json")
            self.assertEqual(code, 0)
            payload = json.loads(out)
        for f in required:
            self.assertIn(f, payload, f"history --json missing '{f}'")

    def test_stats_json_includes_required_fields(self):
        required = _required_fields(_SPEC_DIR / "stats-json.schema.json")
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL, summary="s")
            code, out, _err = run_cli("stats", "--json")
            self.assertEqual(code, 0)
            payload = json.loads(out)
        for f in required:
            self.assertIn(f, payload, f"stats --json missing '{f}'")
        # And the nested coverage object has its required fields.
        coverage_required = (
            json.loads((_SPEC_DIR / "stats-json.schema.json").read_text())
            ["properties"]["coverage"]["required"]
        )
        for f in coverage_required:
            self.assertIn(f, payload["coverage"],
                f"stats --json coverage block missing '{f}'")

    def test_meta_json_includes_required_fields(self):
        required = _required_fields(_SPEC_DIR / "meta.schema.json")
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL, summary="s")
            meta = json.loads((v / "nda" / "x" / "meta.json").read_text())
        for f in required:
            self.assertIn(f, meta, f"meta.json missing '{f}'")

    def test_vault_config_schema_required_present(self):
        required = _required_fields(_SPEC_DIR / "vault-config.schema.json")
        with temp_vault() as v:
            cfg = json.loads((v / ".vault.json").read_text())
        for f in required:
            self.assertIn(f, cfg, f".vault.json missing '{f}'")


class SchemaFilesAreWellFormedTests(unittest.TestCase):
    """The `make spec-check` target enforces this too; pulling it into the
    test suite ensures CI runs it without needing the Makefile target."""

    def test_every_schema_file_parses_as_json(self):
        files = sorted(_SPEC_DIR.glob("*.schema.json"))
        self.assertGreaterEqual(
            len(files), 6,
            f"Expected at least 6 schema files in docs/spec/, found {len(files)}",
        )
        for f in files:
            with self.subTest(schema=f.name):
                doc = json.loads(f.read_text())
                self.assertEqual(doc.get("$schema"),
                    "https://json-schema.org/draft/2020-12/schema",
                    f"{f.name}: expected JSON Schema 2020-12")
                self.assertIn("title", doc)
                self.assertIn("$id", doc)


if __name__ == "__main__":
    unittest.main()
