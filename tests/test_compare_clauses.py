"""compare-clauses command — symmetric and per-clause modes."""

import unittest

from tests._helpers import (
    CliCase, add_template, run_cli, temp_vault,
    SAMPLE_NDA_MUTUAL, SAMPLE_NDA_STARTUP_FRIENDLY,
)


class CompareClausesTests(CliCase):
    def setUp(self):
        self._cm = temp_vault()
        self.vault = self._cm.__enter__()
        add_template(self.vault, "nda", "house", SAMPLE_NDA_MUTUAL)
        add_template(self.vault, "nda", "yc", SAMPLE_NDA_STARTUP_FRIENDLY)

    def tearDown(self):
        self._cm.__exit__(None, None, None)

    def test_symmetric_lists_common_and_unique(self):
        code, out, _err = run_cli("compare-clauses", "nda/house", "nda/yc")
        self.assertEqual(code, 0)
        self.assertIn("Common clauses", out)
        self.assertIn("Term and Survival", out)
        self.assertIn("Only in nda/house", out)
        self.assertIn("Residual Knowledge", out)
        self.assertIn("Only in nda/yc", out)

    def test_symmetric_marks_same_vs_different(self):
        # Make a copy, then mutate one clause body
        add_template(self.vault, "nda", "house2", SAMPLE_NDA_MUTUAL)
        f = self.vault / "nda" / "house2" / "v1.md"
        body = f.read_text().replace("two years", "FIVE years")
        f.write_text(body)
        code, out, _err = run_cli("compare-clauses", "nda/house", "nda/house2")
        self.assertEqual(code, 0)
        self.assertIn("[different]", out)
        # Other clauses untouched → "[same]"
        self.assertIn("[same]", out)

    def test_per_clause_emits_unified_diff(self):
        code, out, _err = run_cli(
            "compare-clauses", "nda/house", "nda/yc",
            "--clause", "Term and Survival",
        )
        self.assertEqual(code, 0)
        self.assertIn("---", out)
        self.assertIn("+++", out)
        self.assertIn("two years", out)
        self.assertIn("one year", out)

    def test_per_clause_unknown_errors(self):
        code, _out, err = run_cli(
            "compare-clauses", "nda/house", "nda/yc",
            "--clause", "No Such Clause",
        )
        self.assertNotEqual(code, 0)
        self.assertIn("not in", err.lower())

    def test_output_deterministic(self):
        a = run_cli("compare-clauses", "nda/house", "nda/yc")
        b = run_cli("compare-clauses", "nda/house", "nda/yc")
        self.assertEqual(a[1], b[1])


if __name__ == "__main__":
    unittest.main()
