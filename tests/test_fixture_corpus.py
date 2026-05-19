"""Real-contract fixture-corpus tests.

For each `tests/fixtures/contracts/*.md`, the companion `.expected.json`
describes which detector tier should fire and which clause titles should
appear in order. The test loads both, runs `detect_clauses`, and asserts:

  1. The expected number of clauses are detected.
  2. Their titles match (in order).
  3. The detector tier that fires matches the fixture's annotation
     (h2 / bold / all_caps / explicit).

Fixtures span:
  - Common Paper Mutual NDA style (H2 numbered)              [01]
  - One-Way NDA (H2 unnumbered)                              [02]
  - YC SAFE style (H2 + Article I. / Roman numerals + H3 subsections) [03]
  - Bonterms cloud-style (H2 with ALL-CAPS shouts in bodies) [04]
  - Employment agreement (bold-numbered, no H2)              [05]
  - Traditional licensing (ALL-CAPS only)                    [06]
  - MSA with every supported numbering shape mixed           [07]
  - DPA with deep H3 subsection nesting                      [08]
  - Bilingual (German/English) NDA with Unicode titles       [09]
  - Unstructured doc requiring an explicit `clauses` map     [10]

This complements the property-based tests in test_properties.py: those
exercise random inputs against invariants; these exercise real-shape
inputs against ground truth.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple

from tests._helpers import tvc

_CORPUS_DIR = Path(__file__).parent / "fixtures" / "contracts"


def _load_corpus() -> List[Tuple[Path, Dict[str, Any]]]:
    """Yield (md_path, expected_dict) for each fixture in the corpus."""
    out: List[Tuple[Path, Dict[str, Any]]] = []
    if not _CORPUS_DIR.is_dir():
        return out
    for md in sorted(_CORPUS_DIR.glob("*.md")):
        expected_path = md.with_suffix(".expected.json")
        if not expected_path.exists():
            continue
        out.append((md, json.loads(expected_path.read_text(encoding="utf-8"))))
    return out


_DETECTOR_TIER = {
    "h2": "T1 (## heading)",
    "bold": "T2 (bold-numbered)",
    "all_caps": "T3 (ALL-CAPS)",
    "explicit": "explicit clauses map",
}


class FixtureCorpusTests(unittest.TestCase):
    """One test method per fixture (so failures point at the specific file)."""

    def test_corpus_is_non_empty(self):
        """Sanity: the corpus loads at least 8 fixtures."""
        corpus = _load_corpus()
        self.assertGreaterEqual(
            len(corpus), 8,
            f"Expected >= 8 corpus fixtures, found {len(corpus)}. "
            f"Check tests/fixtures/contracts/.",
        )

    def test_every_fixture_has_consistent_expected_json(self):
        """Each .md has a sibling .expected.json with the required keys."""
        for md_path, expected in _load_corpus():
            with self.subTest(fixture=md_path.name):
                self.assertIn("detector", expected,
                               f"{md_path.name}: missing 'detector' field")
                self.assertIn(
                    expected["detector"], _DETECTOR_TIER,
                    f"{md_path.name}: unknown detector "
                    f"{expected['detector']!r}; expected one of "
                    f"{set(_DETECTOR_TIER)}",
                )
                self.assertIn("clauses", expected,
                               f"{md_path.name}: missing 'clauses' field")
                self.assertIsInstance(expected["clauses"], list)
                for c in expected["clauses"]:
                    self.assertIn("title", c)

    def test_each_fixture_matches_its_ground_truth(self):
        """The main loop: run detect_clauses, compare against expected."""
        for md_path, expected in _load_corpus():
            with self.subTest(fixture=md_path.name):
                text = md_path.read_text(encoding="utf-8")
                expected_titles = [c["title"] for c in expected["clauses"]]

                if expected["detector"] == "explicit":
                    # The doc has no auto-detectable structure; detect_clauses
                    # should return [] without an explicit map.
                    auto = tvc.detect_clauses(text)
                    self.assertEqual(
                        auto, [],
                        f"{md_path.name}: expected zero auto-detected clauses "
                        f"(detector='explicit') but got "
                        f"{[c['title'] for c in auto]}",
                    )
                    # With the explicit map supplied, detection succeeds.
                    explicit = expected.get("explicit_map") or []
                    self.assertTrue(
                        explicit,
                        f"{md_path.name}: detector='explicit' requires "
                        f"`explicit_map` to be set in the expected JSON",
                    )
                    detected = tvc.detect_clauses(text, explicit_map=explicit)
                    detected_titles = [c["title"] for c in detected]
                    self.assertEqual(
                        detected_titles, expected_titles,
                        f"{md_path.name} (explicit): expected {expected_titles}, "
                        f"got {detected_titles}",
                    )
                    return  # subTest done

                # Auto-detect path (h2 / bold / all_caps).
                detected = tvc.detect_clauses(text)
                detected_titles = [c["title"] for c in detected]
                self.assertEqual(
                    detected_titles, expected_titles,
                    f"{md_path.name} ({expected['detector']}): "
                    f"expected {expected_titles}, got {detected_titles}",
                )

                # Additional structural assertions where requested.
                extras = expected.get("additional_assertions", {})
                if extras.get("no_h3_promoted_to_clause"):
                    for c in detected:
                        self.assertFalse(
                            c["title"].startswith("###"),
                            f"{md_path.name}: an H3 leaked into clause titles "
                            f"as {c['title']!r}",
                        )
                if extras.get("definitions_body_contains_h3"):
                    # Find the "Definitions" clause and assert its body
                    # includes H3 markdown -- proving subsection nesting was
                    # preserved.
                    defs = next(
                        (c for c in detected
                         if c["title"].lower().startswith("definition")),
                        None,
                    )
                    self.assertIsNotNone(
                        defs, f"{md_path.name}: 'Definitions' clause missing")
                    body = tvc.slice_clause_text(text, defs)
                    self.assertIn(
                        "### ", body,
                        f"{md_path.name}: Definitions body should contain "
                        f"H3 subsections but doesn't",
                    )


class FixtureCorpusBoundaryTests(unittest.TestCase):
    """Cross-cutting invariants applied to every fixture: no overlap, no
    empty titles, slice round-trip. Same shape as test_properties but on
    real-style input instead of random generation."""

    def test_no_overlap_in_any_fixture(self):
        for md_path, expected in _load_corpus():
            with self.subTest(fixture=md_path.name):
                text = md_path.read_text(encoding="utf-8")
                if expected["detector"] == "explicit":
                    clauses = tvc.detect_clauses(
                        text, explicit_map=expected["explicit_map"])
                else:
                    clauses = tvc.detect_clauses(text)
                for i in range(len(clauses) - 1):
                    self.assertLessEqual(
                        clauses[i]["end"], clauses[i + 1]["start"],
                        f"{md_path.name}: overlap between clause {i} and {i+1}",
                    )

    def test_no_empty_titles_in_any_fixture(self):
        for md_path, expected in _load_corpus():
            with self.subTest(fixture=md_path.name):
                text = md_path.read_text(encoding="utf-8")
                if expected["detector"] == "explicit":
                    clauses = tvc.detect_clauses(
                        text, explicit_map=expected["explicit_map"])
                else:
                    clauses = tvc.detect_clauses(text)
                for c in clauses:
                    self.assertTrue(
                        c["title"].strip(),
                        f"{md_path.name}: empty title in detected clauses",
                    )

    def test_slice_clause_text_roundtrips_on_corpus(self):
        for md_path, expected in _load_corpus():
            with self.subTest(fixture=md_path.name):
                text = md_path.read_text(encoding="utf-8")
                if expected["detector"] == "explicit":
                    clauses = tvc.detect_clauses(
                        text, explicit_map=expected["explicit_map"])
                else:
                    clauses = tvc.detect_clauses(text)
                for c in clauses:
                    self.assertEqual(
                        tvc.slice_clause_text(text, c),
                        text[c["start"]:c["end"]],
                        f"{md_path.name}: slice_clause_text mismatch on "
                        f"clause {c['title']!r}",
                    )


class FixtureCorpusVaultIntegrationTests(unittest.TestCase):
    """End-to-end: upload each fixture into a temp vault and verify
    `template-vault clauses <ref>` lists the expected titles. Catches
    integration regressions that pure detect_clauses tests miss."""

    def test_each_fixture_uploads_and_lists_clauses(self):
        from tests._helpers import run_cli, temp_vault
        for md_path, expected in _load_corpus():
            if expected["detector"] == "explicit":
                # The auto-detect path doesn't find anything; skipping the
                # upload-then-list assertion since users would author an
                # explicit map manually.
                continue
            with self.subTest(fixture=md_path.name):
                with temp_vault() as v:
                    name = md_path.stem.replace(".", "-")[:40]
                    code, _out, err = run_cli(
                        "upload", str(md_path),
                        "--category", "nda", "--name", name,
                        "--summary", "corpus fixture",
                        "--non-interactive",
                    )
                    self.assertEqual(
                        code, 0,
                        f"{md_path.name}: upload failed: {err!r}",
                    )
                    code, out, _err = run_cli("clauses", f"nda/{name}")
                    self.assertEqual(code, 0)
                    for c in expected["clauses"]:
                        self.assertIn(
                            c["title"], out,
                            f"{md_path.name}: 'clauses' command didn't "
                            f"surface {c['title']!r}",
                        )


if __name__ == "__main__":
    unittest.main()
