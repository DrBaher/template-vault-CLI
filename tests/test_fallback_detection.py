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

    def test_all_caps_minimum_three_chars(self):
        # Spec v1.0: ALL-CAPS heading requires >= 3 chars (was >= 4 here).
        # Multi-token line "IP RIGHTS" qualifies even though "IP" alone wouldn't.
        text = "Preamble.\n\nIP RIGHTS\n\nFirst body.\n\nTERM\n\nSecond body.\n"
        cs = tvc.detect_clauses(text)
        titles = [c["title"] for c in cs]
        self.assertIn("IP RIGHTS", titles)
        self.assertIn("TERM", titles)

    def test_all_caps_single_token_under_four_letters_rejected(self):
        # Spec v1.0: single-token ALL-CAPS lines need >= 4 ASCII letters.
        # "TER" (3 letters) doesn't qualify even though it satisfies the
        # >= 3 chars / blank-line frame structural test.
        text = "Preamble.\n\nTER\n\nFirst body.\n\nIP\n\nSecond body.\n"
        cs = tvc.detect_clauses(text)
        # Both candidates fail the single-token-min-4-letters rule, so
        # fallback finds nothing and detect_clauses returns [].
        self.assertEqual(cs, [])

    def test_all_caps_bracketed_line_does_not_match(self):
        # `[BRACKETED]` placeholders shouldn't be picked up by ALL-CAPS
        # detection. The regex anchors on `[A-Z]` as first char so `[` is
        # excluded naturally; this test guards the behavior.
        text = (
            "Preamble.\n\n"
            "[BRACKETED PLACEHOLDER]\n\n"
            "First body.\n\n"
            "CONFIDENTIALITY OBLIGATIONS\n\n"
            "Second body.\n"
        )
        cs = tvc.detect_clauses(text)
        titles = [c["title"] for c in cs]
        self.assertNotIn("BRACKETED PLACEHOLDER", titles)
        self.assertNotIn("[BRACKETED PLACEHOLDER]", titles)
        # The only heading found is single-line, so the >= 2 threshold
        # means fallback commits nothing.
        self.assertEqual(cs, [])


if __name__ == "__main__":
    unittest.main()
