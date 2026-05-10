"""clause-library — find similar clauses across templates by similarity threshold."""

import unittest

from tests._helpers import (
    CliCase, add_template, run_cli, temp_vault, tvc,
)


# Three NDAs that share a near-identical "Confidentiality" clause and have
# unique "Term" clauses.
SHARED_CONF = (
    "## Confidentiality\n"
    "Each Party shall use the other Party's Confidential Information solely for the "
    "purpose of evaluating the relationship and shall protect it with the same degree "
    "of care it uses for its own Confidential Information, but no less than reasonable care."
)
SHARED_CONF_NEAR = (
    "## Confidentiality\n"
    "Each Party shall use the other Party's Confidential Information only for the "
    "purpose of evaluating the relationship and shall protect it with the same degree "
    "of care it uses for its own Confidential Information, but no less than reasonable care."
)


def _doc(term_body: str, conf_body: str = SHARED_CONF) -> str:
    return f"# Doc\n\n{conf_body}\n\n## Term\n{term_body}\n"


class ClauseLibraryTests(CliCase):
    def setUp(self):
        self._cm = temp_vault()
        self.vault = self._cm.__enter__()
        add_template(self.vault, "nda", "a", _doc("one year"))
        add_template(self.vault, "nda", "b", _doc("two years", SHARED_CONF_NEAR))
        add_template(self.vault, "nda", "c", _doc("three years"))

    def tearDown(self):
        self._cm.__exit__(None, None, None)

    def test_finds_repeated_clause(self):
        code, out, _err = run_cli("clause-library", "--threshold", "0.85")
        self.assertEqual(code, 0)
        # The shared Confidentiality clause across all three should cluster.
        self.assertIn("Confidentiality", out)
        self.assertIn("n=3", out)

    def test_high_threshold_filters_out_near_misses(self):
        code, out, _err = run_cli("clause-library", "--threshold", "0.999")
        self.assertEqual(code, 0)
        # The nearly-identical-but-not-exact Confidentiality clause shouldn't
        # form a 3-member cluster — at 0.999 we expect either no clusters or
        # a 2-member one (a + c, which are byte-identical).
        # Just check we get a reduced set.
        self.assertNotIn("n=3", out)

    def test_low_threshold_finds_more(self):
        code, out, _err = run_cli("clause-library", "--threshold", "0.50")
        self.assertEqual(code, 0)
        self.assertIn("Confidentiality", out)


if __name__ == "__main__":
    unittest.main()
