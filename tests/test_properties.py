"""Property-based tests for clause detection invariants.

Stdlib-only — uses `random` with deterministic seeds instead of `hypothesis`
to keep the no-third-party-dep posture. Each property runs ~50 generated
cases; failures print the seed so they're reproducible.

Invariants tested:
  1. Cascade priority: any doc with >=1 H2 returns exactly the H2 count,
     even if bold-numbered or ALL-CAPS lines are also present.
  2. Clause boundaries don't overlap.
  3. slice_clause_text round-trips text[start:end].
  4. Titles are never empty for detected clauses.
  5. _strip_clause_number is idempotent.
  6. find_clause_by_title prefers exact match over substring.
  7. Alias resolution is symmetric: querying by alias and by canonical
     returns the same clause.
  8. Bold-numbered fallback never fires when H2 fires.
  9. ALL-CAPS fallback never fires when H2 or bold-numbered fires.
"""

from __future__ import annotations

import random
import string
import unittest

from tests._helpers import tvc


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------


def _gen_title(rng: random.Random, n_words: int = -1) -> str:
    """Generate a random Title Case title with 1-4 words."""
    if n_words < 0:
        n_words = rng.randint(1, 4)
    words = []
    for _ in range(n_words):
        word_len = rng.randint(3, 9)
        word = "".join(rng.choices(string.ascii_lowercase, k=word_len))
        words.append(word.capitalize())
    return " ".join(words)


def gen_h2_doc(seed: int, n_clauses: int) -> tuple[str, list[str]]:
    """Build an H2-structured doc with `n_clauses` clauses. Returns
    (text, expected_titles_in_order)."""
    rng = random.Random(seed)
    titles = [_gen_title(rng) for _ in range(n_clauses)]
    parts = ["# Document Title\n\nPreamble line.\n\n"]
    for i, t in enumerate(titles):
        # Mix numbered (50%) and unnumbered styles
        if rng.random() < 0.5:
            parts.append(f"## {i+1}. {t}\n\nBody for clause {i}.\n\n")
        else:
            parts.append(f"## {t}\n\nBody for clause {i}.\n\n")
    return "".join(parts), titles


def gen_bold_doc(seed: int, n_clauses: int) -> tuple[str, list[str]]:
    """Build a bold-numbered doc (no H2 anywhere)."""
    rng = random.Random(seed)
    titles = [_gen_title(rng) for _ in range(n_clauses)]
    parts = ["Document preamble.\n\n"]
    for i, t in enumerate(titles):
        parts.append(f"**{i+1}. {t}**\n\nBody for clause {i}.\n\n")
    return "".join(parts), titles


def gen_all_caps_doc(seed: int, n_clauses: int) -> tuple[str, list[str]]:
    """Build an ALL-CAPS-headed doc (no H2 or bold-numbered anywhere)."""
    rng = random.Random(seed)
    raw_titles = [_gen_title(rng) for _ in range(n_clauses)]
    titles = [t.upper() for t in raw_titles]
    parts = ["Document preamble.\n\n"]
    for i, t in enumerate(titles):
        parts.append(f"{t}\n\nBody for clause {i}.\n\n")
    return "".join(parts), titles


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class CascadePriorityProperty(unittest.TestCase):
    """T1 (H2) wins. T2 (bold-numbered) wins over T3 (ALL-CAPS).
    Tests that fallback tiers never poison T1 results."""

    def test_h2_count_matches_clause_count(self):
        for seed in range(50):
            for n in range(1, 8):
                text, expected = gen_h2_doc(seed, n)
                clauses = tvc.detect_clauses(text)
                self.assertEqual(
                    len(clauses), n,
                    f"seed={seed} n={n}: got {[c['title'] for c in clauses]!r}",
                )
                detected_titles = [c["title"] for c in clauses]
                self.assertEqual(detected_titles, expected, f"seed={seed} n={n}")

    def test_h2_wins_over_injected_bold_or_caps(self):
        """An H2-structured doc that also contains stray bold-numbered and
        ALL-CAPS lines (inside clause bodies) still returns only the H2
        count — the fallback tiers must NOT activate."""
        for seed in range(50):
            for n in range(1, 6):
                text, expected = gen_h2_doc(seed, n)
                # Inject noise into the first clause's body
                injection = (
                    "Inside body: **3.5 SHOULD NOT MATCH** "
                    "and CAPS LINE SHOULD NOT MATCH either.\n\n"
                )
                text = text.replace("Body for clause 0.\n\n",
                                     f"Body for clause 0.\n\n{injection}")
                clauses = tvc.detect_clauses(text)
                self.assertEqual(len(clauses), n,
                                  f"seed={seed} n={n}: fallback bled into "
                                  f"H2 doc; got {len(clauses)}")

    def test_bold_doc_uses_t2(self):
        for seed in range(30):
            for n in range(2, 7):
                text, expected = gen_bold_doc(seed, n)
                clauses = tvc.detect_clauses(text)
                self.assertEqual(
                    len(clauses), n,
                    f"seed={seed} n={n}: got {[c['title'] for c in clauses]}",
                )

    def test_all_caps_doc_uses_t3(self):
        for seed in range(30):
            for n in range(2, 7):
                text, expected = gen_all_caps_doc(seed, n)
                clauses = tvc.detect_clauses(text)
                # ALL-CAPS detection enforces single-token >=4 letters; some
                # generated titles will be single-token <4 letters and won't
                # qualify. Filter expectations the same way:
                qualifying = [
                    t for t in expected
                    if tvc._qualifies_as_all_caps_heading(t)
                ]
                if len(qualifying) >= 2:
                    self.assertEqual(
                        len(clauses), len(qualifying),
                        f"seed={seed} n={n}: qualifying={qualifying!r}, "
                        f"got {[c['title'] for c in clauses]!r}",
                    )


class ClauseBoundariesProperty(unittest.TestCase):
    """Boundaries don't overlap and slice_clause_text round-trips."""

    def test_no_overlap_between_adjacent_clauses(self):
        for seed in range(50):
            for n in range(2, 8):
                text, _ = gen_h2_doc(seed, n)
                clauses = tvc.detect_clauses(text)
                for i in range(len(clauses) - 1):
                    self.assertLessEqual(
                        clauses[i]["end"], clauses[i + 1]["start"],
                        f"seed={seed} n={n} idx={i}: overlap detected",
                    )

    def test_slice_clause_text_roundtrips_text_slicing(self):
        for seed in range(30):
            for n in range(1, 6):
                text, _ = gen_h2_doc(seed, n)
                for c in tvc.detect_clauses(text):
                    sliced = tvc.slice_clause_text(text, c)
                    via_indices = text[c["start"]:c["end"]]
                    self.assertEqual(sliced, via_indices,
                                      f"seed={seed} n={n}: slice mismatch")

    def test_clause_body_starts_at_anchor(self):
        """For H2 detection, the body starts with the `## ` line itself."""
        for seed in range(30):
            for n in range(1, 6):
                text, _ = gen_h2_doc(seed, n)
                for c in tvc.detect_clauses(text):
                    body = tvc.slice_clause_text(text, c)
                    self.assertTrue(body.startswith("## "),
                                     f"seed={seed} n={n}: body doesn't start "
                                     f"with ## (got {body[:20]!r})")


class TitlePropertyTests(unittest.TestCase):
    def test_detected_titles_are_nonempty(self):
        for seed in range(50):
            for n in range(1, 8):
                text, _ = gen_h2_doc(seed, n)
                for c in tvc.detect_clauses(text):
                    self.assertTrue(c["title"].strip(),
                                     f"seed={seed} n={n}: empty title")

    def test_strip_clause_number_is_idempotent(self):
        """Stripping twice produces the same result as stripping once."""
        # Generate a mix of numbering-prefixed and bare titles.
        prefixed = [
            "1. Purpose", "(2) Term", "[3] Notices",
            "Article IV. Indemnity", "Section 5. Limitation",
            "§ 6. Governing Law", "1.2.3 Subsection",
            "Purpose", "Term", "Article",  # bare
        ]
        for s in prefixed:
            once = tvc._strip_clause_number(s)
            twice = tvc._strip_clause_number(once)
            self.assertEqual(
                once, twice,
                f"_strip_clause_number not idempotent on {s!r}: "
                f"once={once!r}, twice={twice!r}",
            )


class FindClauseByTitleProperty(unittest.TestCase):
    def test_exact_match_beats_substring_when_both_present(self):
        """If we have both 'Term' and 'Term and Survival', querying 'Term'
        must return the exact match, not the substring."""
        text = "## Term\nx\n## Term and Survival\ny\n## Confidentiality\nz\n"
        clauses = tvc.detect_clauses(text)
        c = tvc.find_clause_by_title(clauses, "Term")
        self.assertIsNotNone(c)
        self.assertEqual(c["title"], "Term")

    def test_alias_resolves_to_same_clause_as_canonical(self):
        for seed in range(20):
            rng = random.Random(seed)
            canonical = _gen_title(rng, n_words=2)
            alias = _gen_title(rng, n_words=2)
            other = _gen_title(rng, n_words=2)
            # Ensure the three differ
            if len({canonical, alias, other}) < 3:
                continue
            text = f"## {canonical}\nbody-a\n## {other}\nbody-b\n"
            clauses = tvc.detect_clauses(
                text,
                aliases_map={canonical: [alias]},
            )
            c_canonical = tvc.find_clause_by_title(clauses, canonical)
            c_alias = tvc.find_clause_by_title(clauses, alias)
            self.assertIs(c_canonical, c_alias,
                           f"seed={seed} canonical={canonical!r} "
                           f"alias={alias!r}: alias resolution diverged")


class CascadeStrictnessProperty(unittest.TestCase):
    """T1>T2>T3 cascade strictness: a doc with the higher tier must NOT
    activate the lower tier even if lower-tier patterns are present."""

    def test_bold_present_in_h2_doc_does_not_activate_t2(self):
        for seed in range(30):
            for n in range(2, 6):
                text, _ = gen_h2_doc(seed, n)
                text += "**99. Trailing bold heading that should NOT match**\n\n"
                clauses = tvc.detect_clauses(text)
                self.assertEqual(len(clauses), n)
                titles = [c["title"] for c in clauses]
                for t in titles:
                    self.assertNotIn("Trailing bold heading", t)

    def test_caps_present_in_bold_doc_does_not_activate_t3(self):
        for seed in range(30):
            for n in range(2, 6):
                text, _ = gen_bold_doc(seed, n)
                text += "\nTRAILING CAPS LINE\n\nbody\n"
                clauses = tvc.detect_clauses(text)
                titles = [c["title"] for c in clauses]
                for t in titles:
                    self.assertNotIn("TRAILING CAPS LINE", t.upper())


if __name__ == "__main__":
    unittest.main()
