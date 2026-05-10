"""Bold-prefix and ALL-CAPS heading fallback for non-H2 templates."""

import unittest

from tests._helpers import tvc


class FallbackHeadingTests(unittest.TestCase):
    def test_bold_numbered_headings_when_no_h2(self):
        text = (
            "Some preamble.\n\n"
            "**1. Purpose**\n\n"
            "The parties wish to evaluate.\n\n"
            "**2. Term and Survival**\n\n"
            "Two years.\n\n"
            "**3. Confidentiality**\n\n"
            "Reasonable care.\n"
        )
        cs = tvc.detect_clauses(text)
        self.assertEqual(
            [c["title"] for c in cs],
            ["Purpose", "Term and Survival", "Confidentiality"],
        )

    def test_bold_with_word_prefix(self):
        text = (
            "**Section 4. Indemnification**\n\n"
            "Each party indemnifies the other.\n\n"
            "**Section 5. Limitation of Liability**\n\n"
            "Capped at fees paid.\n"
        )
        cs = tvc.detect_clauses(text)
        self.assertEqual(
            [c["title"] for c in cs],
            ["Indemnification", "Limitation of Liability"],
        )

    def test_all_caps_headings_when_no_h2(self):
        text = (
            "Preamble paragraph.\n\n"
            "PURPOSE\n\n"
            "The parties wish to evaluate.\n\n"
            "CONFIDENTIALITY\n\n"
            "Each party shall protect the other's information.\n\n"
            "TERM AND SURVIVAL\n\n"
            "Two years from the Effective Date.\n"
        )
        cs = tvc.detect_clauses(text)
        titles = [c["title"] for c in cs]
        self.assertIn("PURPOSE", titles)
        self.assertIn("CONFIDENTIALITY", titles)
        self.assertIn("TERM AND SURVIVAL", titles)

    def test_h2_wins_over_fallback(self):
        # When H2 detection finds at least one clause, the fallback never runs
        # — even if there's a bold-numbered heading lurking in the body.
        text = (
            "## 1. Purpose\nbody\n\n"
            "## 2. Confidentiality\nbody\n\n"
            "**3. Sneaky bold heading**\n\nshould stay in body 2"
        )
        cs = tvc.detect_clauses(text)
        self.assertEqual([c["title"] for c in cs], ["Purpose", "Confidentiality"])
        # And the bold line stays inside the Confidentiality clause body:
        body = tvc.slice_clause_text(text, cs[1])
        self.assertIn("Sneaky bold heading", body)

    def test_fallback_returns_empty_for_unstructured_prose(self):
        text = "Just some prose. No headings.\n\nMore prose.\n\nEnd."
        self.assertEqual(tvc.detect_clauses(text), [])

    def test_single_match_does_not_trigger_fallback(self):
        # Need at least 2 fallback matches to commit — a single bold line
        # inside prose isn't a heading.
        text = "Some text.\n\n**1. Maybe a heading?**\n\nMore text."
        self.assertEqual(tvc.detect_clauses(text), [])


if __name__ == "__main__":
    unittest.main()
