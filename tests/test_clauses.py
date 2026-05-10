"""Clause auto-detection and explicit-map override."""

import unittest

from tests._helpers import (
    CliCase, add_template, run_cli, temp_vault, tvc,
    SAMPLE_NDA_MUTUAL,
)


class ClauseDetectTests(unittest.TestCase):
    def test_h2_only_not_h3(self):
        text = ("## 1. A\nbody\n\n### 1.1 sub\nsub-body\n\n## 2. B\nbody-b\n")
        clauses = tvc.detect_clauses(text)
        titles = [c["title"] for c in clauses]
        self.assertEqual(titles, ["A", "B"])
        self.assertIn("sub-body", tvc.slice_clause_text(text, clauses[0]))
        self.assertIn("body-b", tvc.slice_clause_text(text, clauses[1]))

    def test_unnumbered_h2(self):
        text = "## Purpose\nx\n## Term\ny\n"
        cs = tvc.detect_clauses(text)
        self.assertEqual([c["title"] for c in cs], ["Purpose", "Term"])

    def test_numbered_with_paren(self):
        text = "## 1) Purpose\nx\n## 2) Term\ny\n"
        cs = tvc.detect_clauses(text)
        self.assertEqual([c["title"] for c in cs], ["Purpose", "Term"])

    def test_mixed_numbered_unnumbered(self):
        text = "## 1. Purpose\nx\n## Term\ny\n## 3. Survival\nz\n"
        cs = tvc.detect_clauses(text)
        self.assertEqual([c["title"] for c in cs], ["Purpose", "Term", "Survival"])

    def test_no_h2_returns_empty(self):
        text = "frontmatter\n# top heading\nstuff\n"
        self.assertEqual(tvc.detect_clauses(text), [])

    def test_explicit_map_overrides_autodetect(self):
        text = "## 1. Foo\nbar\n## 2. Baz\nqux\n"
        explicit = [
            {"title": "Foo Custom", "anchor": "## 1. Foo"},
            {"title": "Baz Custom", "anchor": "## 2. Baz"},
        ]
        cs = tvc.detect_clauses(text, explicit_map=explicit)
        self.assertEqual([c["title"] for c in cs], ["Foo Custom", "Baz Custom"])

    def test_explicit_map_skips_missing_anchor(self):
        text = "## 1. Foo\nbar\n"
        explicit = [
            {"title": "Foo", "anchor": "## 1. Foo"},
            {"title": "Bogus", "anchor": "## 99. Missing"},
        ]
        cs = tvc.detect_clauses(text, explicit_map=explicit)
        self.assertEqual([c["title"] for c in cs], ["Foo"])

    def test_first_and_last_clause_boundaries(self):
        text = "preamble\n\n## A\nbody-a\n\n## B\nbody-b ends here"
        cs = tvc.detect_clauses(text)
        self.assertEqual(len(cs), 2)
        a_body = tvc.slice_clause_text(text, cs[0])
        b_body = tvc.slice_clause_text(text, cs[1])
        self.assertTrue(a_body.startswith("## A"))
        self.assertIn("body-a", a_body)
        self.assertNotIn("body-b", a_body)
        self.assertTrue(b_body.startswith("## B"))
        self.assertIn("body-b", b_body)

    def test_clause_with_no_body(self):
        text = "## Empty\n## Next\nbody\n"
        cs = tvc.detect_clauses(text)
        self.assertEqual([c["title"] for c in cs], ["Empty", "Next"])
        self.assertEqual(tvc.slice_clause_text(text, cs[0]).strip(), "## Empty")


class ClauseFindTests(unittest.TestCase):
    def test_find_by_title_case_insensitive(self):
        cs = tvc.detect_clauses(SAMPLE_NDA_MUTUAL)
        c = tvc.find_clause_by_title(cs, "term and survival")
        self.assertIsNotNone(c)
        self.assertEqual(c["title"], "Term and Survival")

    def test_find_by_substring(self):
        cs = tvc.detect_clauses(SAMPLE_NDA_MUTUAL)
        c = tvc.find_clause_by_title(cs, "Survival")
        self.assertIsNotNone(c)
        self.assertEqual(c["title"], "Term and Survival")

    def test_find_returns_none_when_missing(self):
        cs = tvc.detect_clauses(SAMPLE_NDA_MUTUAL)
        self.assertIsNone(tvc.find_clause_by_title(cs, "Indemnity"))


class ClausesCommandTests(CliCase):
    def test_clauses_lists_titles(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            code, out, _err = run_cli("clauses", "nda/x")
            self.assertEqual(code, 0)
            self.assertIn("Purpose", out)
            self.assertIn("Term and Survival", out)
            self.assertIn("Residual Knowledge", out)
            # H3 subsection should NOT appear as its own clause
            self.assertNotIn("Scope", out)


if __name__ == "__main__":
    unittest.main()
