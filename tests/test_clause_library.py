"""clause-library — find similar clauses across templates by similarity threshold."""

import json
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


class ClauseLibraryExtractTests(CliCase):
    def setUp(self):
        self._cm = temp_vault()
        self.vault = self._cm.__enter__()
        add_template(self.vault, "nda", "a", _doc("one year"))
        add_template(self.vault, "nda", "b", _doc("two years", SHARED_CONF_NEAR))
        add_template(self.vault, "nda", "c", _doc("three years"))

    def tearDown(self):
        self._cm.__exit__(None, None, None)

    def test_extract_all_writes_clause_file(self):
        code, out, _err = run_cli(
            "clause-library", "--threshold", "0.85",
            "--extract", "--yes-extract-all",
        )
        self.assertEqual(code, 0)
        dest = self.vault / "clauses" / "nda" / "confidentiality.md"
        self.assertTrue(dest.exists(), f"expected {dest} to exist")
        body = dest.read_text()
        # Provenance comment with the source templates
        self.assertIn("extracted by template-vault clause-library", body)
        self.assertIn("nda/a@v1", body)
        # The clause body itself
        self.assertIn("## Confidentiality", body)
        self.assertIn("solely for the purpose", body)
        self.assertIn("wrote:", out)

    def test_extract_skips_existing_files(self):
        run_cli("clause-library", "--threshold", "0.85",
                "--extract", "--yes-extract-all")
        # Run again — should skip
        code, out, _err = run_cli(
            "clause-library", "--threshold", "0.85",
            "--extract", "--yes-extract-all",
        )
        self.assertEqual(code, 0)
        self.assertIn("already exists", out)

    def test_extract_non_interactive_without_yes_all_refuses(self):
        # stdin is not a tty in the test runner.
        code, _out, err = run_cli(
            "clause-library", "--threshold", "0.85", "--extract")
        self.assertNotEqual(code, 0)
        self.assertIn("non-interactive", err.lower())

    def test_extract_does_not_treat_clauses_dir_as_category(self):
        # After extracting, re-running clause-library shouldn't pick up the
        # clauses/ dir as another set of templates (no meta.json there).
        run_cli("clause-library", "--threshold", "0.85",
                "--extract", "--yes-extract-all")
        code, out, _err = run_cli("clause-library", "--threshold", "0.85")
        self.assertEqual(code, 0)
        # Still finds the original confidentiality cluster, not duplicated
        self.assertEqual(out.count("- Confidentiality "), 1)


class ClauseLibraryHeaderStripTests(CliCase):
    """Headers like '## 4. Foo' vs '## 7. Foo' should not depress the
    similarity ratio — the comparison must run on the body without the header."""

    def test_clauses_with_different_numbering_still_cluster(self):
        with temp_vault() as v:
            shared = (
                "Each Party shall protect the Confidential Information of the "
                "other Party using the same degree of care it uses for its own."
            )
            doc_a = f"# A\n\n## 4. Confidentiality\n{shared}\n\n## Term\nx\n"
            doc_b = f"# B\n\n## 7. Confidentiality\n{shared}\n\n## Term\ny\n"
            add_template(v, "nda", "a", doc_a)
            add_template(v, "nda", "b", doc_b)
            # 0.999 threshold — only succeeds if the header is excluded from
            # the similarity comparison (the bodies after the header are byte
            # identical; the headers differ on the digit).
            code, out, _err = run_cli("clause-library", "--threshold", "0.999")
            self.assertEqual(code, 0)
            self.assertIn("Confidentiality", out)
            self.assertIn("n=2", out)


class ClauseLibraryAliasClusterTests(CliCase):
    """Templates that name the same clause differently can still cluster, as
    long as one of them declares the equivalence in clause_aliases."""

    def test_aliases_collapse_titles_into_one_cluster(self):
        with temp_vault() as v:
            shared = (
                "This agreement shall remain in effect for the period of "
                "evaluation. Confidentiality obligations survive termination."
            )
            doc_a = f"# A\n\n## 1. Term and Survival\n{shared}\n"
            doc_b = f"# B\n\n## 1. Termination\n{shared}\n"
            add_template(v, "nda", "a", doc_a)
            add_template(v, "nda", "b", doc_b)
            # Declare the equivalence on template a only.
            meta = json.loads((v / "nda" / "a" / "meta.json").read_text())
            meta["clause_aliases"] = {"Term and Survival": ["Termination"]}
            (v / "nda" / "a" / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")

            code, out, _err = run_cli("clause-library", "--threshold", "0.85")
            self.assertEqual(code, 0)
            # Two distinct titles fold into one cluster.
            self.assertIn("n=2", out)
            # The non-canonical title is annotated so the output stays honest.
            self.assertIn("(as 'Termination')", out)

    def test_no_alias_means_no_cross_title_cluster(self):
        with temp_vault() as v:
            shared = "Some shared body text that's identical across two clauses."
            doc_a = f"# A\n\n## 1. Term and Survival\n{shared}\n"
            doc_b = f"# B\n\n## 1. Termination\n{shared}\n"
            add_template(v, "nda", "a", doc_a)
            add_template(v, "nda", "b", doc_b)
            # No clause_aliases — these stay separate buckets and won't form
            # a 2-member cluster.
            code, out, _err = run_cli("clause-library", "--threshold", "0.85")
            self.assertEqual(code, 0)
            self.assertNotIn("n=2", out)


class ClauseLibrarySuggestAliasesTests(CliCase):
    """Suggester surfaces clause pairs that have similar bodies but
    different titles AND aren't already aliased."""

    def test_suggests_pair_with_different_titles_and_similar_body(self):
        with temp_vault() as v:
            shared = (
                "This agreement remains in effect for the period of "
                "evaluation. Confidentiality obligations survive termination."
            )
            add_template(v, "nda", "a", f"# A\n\n## 1. Term and Survival\n{shared}\n")
            add_template(v, "nda", "b", f"# B\n\n## 1. Termination\n{shared}\n")
            code, out, _err = run_cli(
                "clause-library", "--threshold", "0.85", "--suggest-aliases",
            )
            self.assertEqual(code, 0)
            self.assertIn("Alias suggestions", out)
            self.assertIn("Term and Survival", out)
            self.assertIn("Termination", out)

    def test_does_not_suggest_when_already_aliased(self):
        with temp_vault() as v:
            shared = "Identical body text across both templates."
            add_template(v, "nda", "a", f"## 1. Term and Survival\n{shared}\n")
            add_template(v, "nda", "b", f"## 1. Termination\n{shared}\n")
            # Declare the alias on a; the suggester should NOT re-suggest.
            mp = v / "nda" / "a" / "meta.json"
            meta = json.loads(mp.read_text())
            meta["clause_aliases"] = {"Term and Survival": ["Termination"]}
            mp.write_text(json.dumps(meta, indent=2) + "\n")
            code, out, _err = run_cli(
                "clause-library", "--threshold", "0.85", "--suggest-aliases",
            )
            self.assertEqual(code, 0)
            self.assertIn("no alias suggestions", out.lower())


if __name__ == "__main__":
    unittest.main()
