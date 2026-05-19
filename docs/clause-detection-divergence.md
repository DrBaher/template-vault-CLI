# Clause-detection divergence: template-vault-CLI vs compare-cli spec v1.0

This document is the **precise enumeration** of where this repo's
implementation of the four-tier clause-detection cascade differs from
the portable spec at
[compare-cli/docs/clause-detection.md](https://github.com/DrBaher/compare-cli/blob/main/docs/clause-detection.md).

It's a reference for the future reconciliation work — not a roadmap, not
a list of bugs. Some divergences are intentional and should stay;
others are accidents of independent implementation and should converge.
Each row says which.

The cascade order itself (H2 → bold-prefix → ALL-CAPS → synthetic) is
identical in both implementations. The divergences below are inside
individual tiers.

## The divergences

### 1. T1 (H2) — whitespace character class

| | Rule |
|---|---|
| Spec | `^##\s+(.+?)\s*$` |
| Here | `^##[ \t]+(.+?)[ \t]*$` |

`\s` matches more characters (including `\f`, `\v`, line separators) than
`[ \t]`. In practice no real-world template uses those characters in the
heading line, so this divergence is **invisible**. Accept.

### 2. T2 (bold-prefix) — supported numbering shapes

| | Rule |
|---|---|
| Spec | only `\d+(?:\.\d+)*\.?` — pure-digit prefixes |
| Here | also `Article 4.`, `Section IV.`, `Sec. 4.`, `Art. 4.`, `Clause 7.`, `Part II.`, `§ 4.`, and `(N)` paren form |

template-vault is intentionally broader because DOCX-converted contracts
frequently use word-prefixed numbering. The spec could be widened to
match, or this repo could keep its superset and document it as a
permitted extension. **Recommend: widen the spec.** (Action lives on the
compare-cli side, not here.)

### 3. T2 (bold-prefix) — title capture

| | Rule |
|---|---|
| Spec | capture group includes the number — `"1. Purpose"` |
| Here | capture group is the title only — `"Purpose"` (number stripped via `_strip_clause_number`) |

template-vault normalizes titles for clause-key matching across
`swap` / `upgrade` / aliases (so `"## 4. Term"` and `"## Term"` are the
same clause). compare-cli captures the literal text because it diffs at
the line level. Both are correct for their use. **Accept the divergence**
and document that titles in template-vault are normalized at capture
time.

### 4. T3 (ALL-CAPS) — minimum character count

| | Rule |
|---|---|
| Spec | ≥3 characters |
| Here | ≥4 characters (regex `[A-Z][A-Z0-9 \-/&,]{3,}[A-Z0-9]` = 1 + 3 + 1 minimum) |

Real-world ALL-CAPS section markers (`TERM`, `IP`) at length 2-3 are rare
but exist. **Recommend: align with the spec at ≥3.** Cheap one-character
regex change here: `{2,}` instead of `{3,}`. Add tests for the new
3-character single-token case.

### 5. T3 (ALL-CAPS) — blank-line framing

| | Rule |
|---|---|
| Spec | not required — any qualifying line in any position is a heading |
| Here | required — regex anchors to `\n\n` on both sides |

template-vault is stricter because un-framed ALL-CAPS bursts inside
prose (`PLEASE DO NOT REDISTRIBUTE`, contract-text shouts) would
otherwise be detected as headings and corrupt swap/upgrade. The spec
takes the opposite trade-off: more recall, more risk of false
positives. **Recommend: keep the blank-line requirement here** and add
it as an option to the spec (`require_blank_frame` flag). Action on
compare-cli side.

### 6. T3 (ALL-CAPS) — bracketed-line exclusion

| | Rule |
|---|---|
| Spec | excludes lines starting with `[` (so `[BRACKETED]` doesn't trigger) |
| Here | no explicit exclusion |

template-vault doesn't currently exclude `[BRACKETED]` lines from ALL-CAPS
matching. In practice, `[BRACKETED]` placeholders are mixed case
(`[Party A]`) and don't qualify as ALL-CAPS anyway, so this divergence
is **invisible**. **Recommend: add the exclusion here for spec
conformance and future-proofing.** One-character regex change.

### 7. T3 (ALL-CAPS) — single-token rule

| | Rule |
|---|---|
| Spec | single-token lines need ≥4 ASCII letters (`TERM` yes, `OK` no) |
| Here | no specific rule; the ≥4-char total enforces a similar minimum but counts non-letters |

template-vault's `[A-Z0-9 \-/&,]` class permits non-letter characters,
so `T1-A` (4 chars but 2 letters) would qualify. The spec is strictly
"≥4 ASCII letters" for single tokens. **Recommend: tighten this repo's
single-token rule.** Small regex split: multi-token uses the current
class; single-token requires `[A-Z]{4,}`.

### 8. T4 (synthetic) — fallback behavior

| | Rule |
|---|---|
| Spec | if T1-T3 all empty, the whole document becomes one clause titled `"Document"` |
| Here | if T1-T3 all empty, `detect_clauses` returns `[]` |

This is the **biggest semantic divergence**. compare-cli always has at
least one clause to diff against; template-vault prefers empty + an
explicit hint to the user (`cmd_clauses` prints "no clauses detected —
use H2 or supply an explicit `clauses` map"). Reasons to keep the
current behavior:

- The downstream commands (`swap`, `compose`, `upgrade`) assume
  detected clauses are real. A synthetic `"Document"` clause would
  pollute `clause_overrides[]` if swapped.
- The explicit-map escape hatch is the prescribed remedy for
  unstructured templates.

**Recommend: accept the divergence**, document it loudly. compare-cli's
synthetic clause is a drift-detection construct (it lets the tool diff
*something* even when neither version has headings); it doesn't fit
template-vault's storage-and-composition model.

### 9. Body resolution — title-line inclusion

| | Rule |
|---|---|
| Spec | body text starts *after* the heading line |
| Here | body includes the heading line (so `slice_clause_text` returns `"## 4. Foo\n\nbody"`) |

template-vault preserves the heading line in the body for two reasons:

1. `swap` preserves the target's H2 anchor — it splits the replacement
   body on the first `\n` and substitutes only the body-after-header
   from the source.
2. `clause-library` clusters across templates; the v0.3 fix was to strip
   the header line *only at comparison time* (via `_strip_header_line`),
   not in storage.

The spec's choice (exclude header from body) is cleaner for diff
output. **Recommend: accept the divergence.** template-vault's choice
is load-bearing for swap; changing it would cascade through 3-4
commands.

### 10. Body resolution — pre-first-title content

| | Rule |
|---|---|
| Spec | content before the first heading is discarded |
| Here | content before the first heading becomes preamble of the first clause (boundary anchor) |

Real-world contracts have non-trivial preambles ("This Agreement is
entered into on...") that legal teams want preserved. **Recommend:
accept the divergence**, document that template-vault preserves
preamble while compare-cli discards.

## What "reconciliation" would look like

Concrete deltas where I'd recommend **this repo** change to match the spec:

- **Item 4**: ≥4 → ≥3 ALL-CAPS minimum char count. One-character regex
  edit + 1-2 new tests. Safe; widens recall on edge templates.
- **Item 6**: add `[`-prefix exclusion. One small regex edit + 1 test.
  Guards against the `[BRACKETED]` corner case.
- **Item 7**: split single-token vs multi-token ALL-CAPS rules. Small
  regex split + 2 new tests. Tightens precision on single tokens like
  `T1-A`.

Concrete deltas where the **compare-cli spec** would change to match
this repo:

- **Item 2**: widen the T2 numbering shapes to include word-prefixed
  forms and paren-numbered forms.
- **Item 5**: add a `require_blank_frame` option for T3.

Divergences where **both sides should stay as-is** (with this doc as
the rationale): items 1, 3, 8, 9, 10.

## When to do the work

Not now. Both implementations are working for their respective
consumers. The pre-condition for reconciliation is a shared test
fixture set: a corpus of ~30-50 contracts with hand-labeled clause
boundaries that both implementations run against. Until that exists,
"alignment" is a moving target.

If/when the fixture set is built, this document is the punch-list.
