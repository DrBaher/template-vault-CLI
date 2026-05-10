# Architecture

## Storage model

The vault is a **plain Git repository**. There is no database, no daemon, no
SaaS. Multi-user sync is whatever Git remote you already use.

### Vault config (`.vault.json`)

```json
{
  "schema_version": 1,
  "created": "2026-05-10",
  "sources": [],
  "template_defaults": {
    "license": "internal-only",
    "owner": "legal-team",
    "jurisdiction": ["California"]
  },
  "clause_aliases": {
    "Term and Survival": ["Termination", "Duration"]
  }
}
```

`template_defaults` is a partial `meta.json`: any field absent or empty in
a per-template meta gets filled from this map at read time via
`load_meta_resolved`. Per-template values always win on key collision. The
overlay is **never** persisted back into the per-template files — mutating
commands round-trip through raw `load_meta` / `save_meta`.

`clause_aliases` is a vault-wide alias map; per-template `clause_aliases`
are unioned with vault-level entries for the same canonical title.



```
your-vault/
├── .vault.json         ← vault config: schema version, defaults, optional pinned hashes
├── nda/                ← top-level dirs are categories
│   └── house-mutual/   ← each template is a directory
│       ├── v1.md       ← versioned files (any extension)
│       ├── v2.md
│       └── meta.json   ← exactly one per template directory
├── investment/
└── msa/
```

Categories are conventional but not enforced (`doctor` warns on unrecognized
ones). Versioned files use any extension; `meta.json` records the canonical
ordering and the latest pointer.

## `meta.json` schema (v1)

```json
{
  "name": "house-mutual",
  "category": "nda",
  "latest_version": "v3",
  "versions": [
    {"id": "v1", "added": "2023-04-12", "supersedes": null,  "supersedes_by": "v2", "changelog": "initial"},
    {"id": "v2", "added": "2024-01-08", "supersedes": "v1",  "supersedes_by": "v3", "changelog": "tightened residuals"},
    {"id": "v3", "added": "2024-09-21", "supersedes": "v2",  "changelog": "trade-secret carve-out"}
  ],
  "jurisdiction": ["California", "Delaware"],
  "party_type": ["mutual"],
  "deal_type": ["partnership", "vendor"],
  "tags": ["short-form", "house-style"],
  "owner": "legal-team",
  "license": "private",
  "source": null,
  "uploaded_by": "@username",
  "use_count": 47,
  "last_used": "2026-04-30",
  "summary": "Short-form mutual NDA for partnership / vendor diligence …",

  "derived_from": null,
  "forked_at_parent_version": null,
  "clauses": null,
  "clause_overrides": [],
  "clause_aliases": {}
}
```

Required: `name`, `category`, `latest_version`, `versions[]`. The four
"composition" fields default to inert values; they're populated by `compose`
and `swap`. `summary` is informally required — without it `find` and `ask`
recall is much weaker.

## Search algorithm

`find` is intentionally tiny:

1. Build a haystack per template = `category + name + summary + tags +
   jurisdiction + deal_type + party_type`, lowercased.
2. If the (lowercased) query is a substring, score = 2.0.
3. Otherwise score = `difflib.SequenceMatcher(None, query, haystack).ratio()`.
4. Return matches with score ≥ 0.30, ranked desc, capped at `--top-k`.

This is deliberately simpler than embeddings or BM25. The vault is rarely
larger than a few hundred templates and the metadata is usually the right
answer; LLM-conversational retrieval (`ask`) is the fallback for fuzzier needs.

## Clause auto-detection

A clause is a section that starts with an H2 (`## Heading`). The regex is:

```python
H2_RE = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)
```

Subsections (`### Foo`, `#### Bar`) are intentionally **not** treated as
clauses — they belong to the body of their parent H2. This convention matches
Common Paper, YC SAFE, Bonterms, and most professional templates.

A clause's body runs from its `^## ` line to the next `^## ` line (or EOF).

### Fallback detection (non-Markdown templates)

If H2 detection returns **zero** clauses, a fallback pass runs. It tries
two patterns, accepting the first that produces ≥ 2 matches:

1. **Bold-numbered headings** like `**1. Purpose**`, `**Section 4. Term**`,
   `**(1) Notices**`. The numbering token is required — bare bold lines
   without a number/word-prefix marker are ignored to avoid snagging inline
   emphasis.
2. **ALL-CAPS standalone lines** of ≥ 4 characters, surrounded by blank
   lines: `CONFIDENTIALITY OBLIGATIONS`. Inline shouts inside a paragraph
   are not matched (the surrounding-blank-lines requirement filters those).

The fallback is intentionally conservative. False negatives (zero clauses)
are recoverable via the explicit `clauses` map; false positives (a clause
inside a body) corrupt swap/upgrade silently. The fallback never runs when
H2 detection has produced any clauses.

This is what makes `.docx` → Markdown templates work after `upload`'s
heading-style conversion: the converter emits `## Heading 2` style for
non-`Heading 1` paragraphs, and H2 detection takes over.

### Title normalization

For matching by title (in `swap`, `compare-clauses`, `upgrade`), titles are
case-insensitively compared after stripping a leading numbering token. The
supported prefix shapes are:

```
"## 4. Term and Survival"          → "Term and Survival"
"## 4) Term and Survival"          → "Term and Survival"
"## (4) Term and Survival"         → "Term and Survival"
"## [4] Term and Survival"         → "Term and Survival"
"## 4.2 Term and Survival"         → "Term and Survival"
"## 4.2.1 Term and Survival"       → "Term and Survival"
"## Article 4. Term and Survival"  → "Term and Survival"
"## Article IV. Term and Survival" → "Term and Survival"
"## Section 4. Term and Survival"  → "Term and Survival"
"## § 4. Term and Survival"        → "Term and Survival"
"## Clause 4. Term and Survival"   → "Term and Survival"
"## Term and Survival"             → "Term and Survival"
```

A swap that names `"Term and Survival"` matches all of these. Unprefixed
titles are returned unchanged. Bare Roman numerals (`## IV. Term`) without
the `Article`/`Section` word are **not** stripped — too risky a false-positive
on titles that happen to start with `I`/`V`. Use the explicit map below for
that case.

### Looking up clauses by name

`find_clause_by_title(clauses, query)` resolves a user-supplied name to a
specific clause. The order is:

1. **Exact match** on the normalized title or any declared alias.
2. **Substring match** on the title or any alias.
3. If step 2 finds **more than one** distinct clause, raise `VaultError`
   listing the candidates instead of silently picking the first. The user
   can re-run with the full title to disambiguate.

This matters because the substring fallback used to silently shadow real
ambiguity — `--clause "term"` could match either "Term and Survival" or
"Termination" depending on document order. The new behavior surfaces the
ambiguity.

### Aliases (`clause_aliases`)

A template's `meta.json` may declare alternate names for a clause:

```json
"clause_aliases": {
  "Term and Survival": ["Termination", "Duration of Obligations"]
}
```

The key must match a real (auto-detected or explicitly mapped) clause title;
the values are alternate names accepted by `swap --clause …`,
`compare-clauses --clause …`, and `upgrade`. Aliases are normalized the same
way as titles, so `"1. Termination"` works as an alias for "Term and Survival".

`doctor` flags `clause_aliases` keys that don't resolve to any detected
clause title in the template.

`clause-library` builds a vault-wide equivalence union over all templates'
aliases — declaring `"Term and Survival": ["Termination"]` on **any one**
template tells the clustering pass to put both titles in the same bucket
across the whole vault. Clusters annotate non-canonical members so the
output stays honest:

```
- Term and Survival  (n=2, mean_similarity=0.91)
    · nda/house@v1
    · nda/yc@v1  (as 'Termination')
```

### Explicit clauses map

If a template doesn't follow the H2 convention, it can supply an explicit
`clauses` list in `meta.json`:

```json
"clauses": [
  {"title": "Purpose",                                "anchor": "## 1. Purpose"},
  {"title": "Definition of Confidential Information", "anchor": "## 2. Definition of Confidential Information"}
]
```

When present, the explicit map takes precedence over auto-detection. The
`anchor` is matched as a literal substring; `doctor` flags anchors that don't
appear in the file.

## Composition primitives

### Why this is more than "Common Paper + a folder + grep"

The CLI treats clauses as first-class structural objects with provenance.
That's something an LLM-only approach cannot replicate, because it has no
memory of:

- which version of which parent your fork was based on,
- which clauses you swapped in from elsewhere,
- which upstream improvements you've already merged in vs. consciously declined.

This information is recorded in `meta.json` (`derived_from`,
`forked_at_parent_version`, `clause_overrides[]`) and is the ground truth that
`upgrade` consults. An LLM can recommend `compose`/`swap` invocations, but the
execution is deterministic — and the result is reproducible from `meta.json`
alone, with no LLM in the loop.

### The contract

The CLI **moves clauses around** between templates. It does **not generate**
clause text. If you want new language, edit by hand or invoke a separate tool.
The line stays clean: deterministic structure tools here, optional LLM
augmentation through `ask`, generation is out of scope.

### `swap` semantics in detail

`swap nda/X --clause "Term and Survival" --from nda/Y`:

1. Auto-detect (or load explicit) clauses in both X and Y.
2. Find the named clause in Y (case-insensitive on the title; substring
   fallback). If absent, fail fast with the list of available clauses.
3. Find the named clause in X. If absent, fail fast similarly.
4. Replace X's clause body with Y's clause body, **preserving X's H2 header
   line** so X's existing numbering ("## 4. Term and Survival") is retained.
5. Append `{clause_title, source_template, source_version, swapped_at}` to
   X's `clause_overrides`.

Body boundaries are anchored on H2 headers, so `swap` preserves frontmatter,
intermediate H1 headings, and signature blocks at the end of the file.

### `upgrade` semantics

For a derived template `nda/house-mutual-startup` whose `derived_from` is
`nda/house-mutual@v3`:

1. Detect parent's current latest version. If unchanged, no-op.
2. Per-clause diff: parent@`forked_at_parent_version` vs parent@latest.
3. For each changed clause:
   - If the clause is in `clause_overrides`, **skip silently** (the user
     deliberately put a different body there).
   - Otherwise show the diff, ask the user to accept (or `--accept-all`), and
     replace the clause in the derived template.
4. Write a new derived version, update `forked_at_parent_version` to the new
   parent latest.

This means a derived template's locally-swapped clauses are stable across
parent updates — exactly the behavior an LLM-only workflow can't promise.

## Clause library (cross-template extraction)

`clause-library` finds clauses that recur near-identically across multiple
templates and (optionally) extracts the canonical text into a reusable file
under `clauses/<category>/<slug>.md`.

### Clustering

1. **Build an equivalence map.** Walk every template's `clause_aliases` and
   union each (title, alias) pair into a single string-keyed union-find. The
   representative is the lexicographically smallest member of each class —
   deterministic across runs.
2. **Bucket occurrences** by union-find representative (not raw title). This
   is what lets `"Term and Survival"` and `"Termination"` cluster together
   when an alias is declared on either side.
3. **Cluster within a bucket.** Greedy single-pass: take the first unconsumed
   occurrence as the cluster seed, then add any other occurrence whose body's
   `difflib.SequenceMatcher.ratio()` against the seed is at least
   `--threshold` (default `0.85`). Members consumed by one cluster cannot
   start or join another. Comparison runs on the body **with the H2 header
   line stripped**, because `## 4. Foo` and `## 7. Foo` have byte-identical
   bodies but different headers; including the header line was depressing
   the ratio and under-clustering. O(n²) per bucket; n is small in practice.
4. **Sort clusters** by descending member count, then descending mean
   similarity, then alphabetically by title.

The threshold is intentionally tunable. `0.85` catches "same clause with party
names swapped"; `0.95` only catches near-byte-identical copies; `0.70` starts
catching clauses that have been edited but share structure.

### Extraction

`--extract` writes each cluster's seed body (which already starts with its `##`
header) to `clauses/<seed-template-category>/<slug>.md`. The slug is the title
lowercased, hyphenated, stripped of non-`[a-z0-9-]` chars. A provenance HTML
comment is prepended:

```
<!-- extracted by template-vault clause-library on 2026-05-10 from: nda/house@v3, nda/yc@v1 -->

## Term and Survival
…
```

Existing files are preserved; the command never overwrites. In an interactive
TTY the user confirms each cluster individually (`[y/N]`); in a non-interactive
context the command refuses unless `--yes-extract-all` is passed, which writes
every cluster non-interactively.

The `clauses/` directory is **not** itself a template directory — `iter_templates`
skips a top-level `clauses/` folder so extracted clause files don't show up in
`list`, `find`, or future `clause-library` runs.

## LLM `ask` design

```
                          ┌─────────────┐
  query  ───────────────► │             │
                          │  build      │  metadata-only listing
                          │  listing    │  (or +500-char excerpts under
                          │             │   --with-content)
  vault meta ───────────► │             │
                          └──────┬──────┘
                                 │
                                 ▼
                          system prompt
                          + listing + query
                                 │
                                 ▼
                          LLM (anthropic | openai-compatible)
                                 │
                                 ▼
                           plain-text answer
```

The system prompt is:

> *You are an assistant helping a user select or compose the best-fit legal
> template from their organization's library. You will be given a list of
> templates with metadata and clause titles, plus a user query. Recommend the
> top match and 1-2 alternatives, with brief reasoning that references each
> template's metadata. If the query asks for composition, emit a sequence of
> `compose` and `swap` commands using only template names and clause titles
> that appear in the listing. Do NOT invent templates or clauses that aren't
> in the list. Reply in plain text, not JSON.*

By default, `ask` does **not** execute LLM-suggested commands. The LLM emits
literal `template-vault swap …` strings and the user copies them into a shell.
This keeps the loop deterministic and reviewable, and an LLM hallucination
becomes an obvious "command not found" rather than a corrupted template.

`ask --execute` opts into running suggestions automatically, with two
guardrails: (1) only `compose` and `swap` lines are eligible — `upload`,
`import`, `publish`, etc. are skipped with a notice; (2) the chain stops on the
first command that exits non-zero. In interactive contexts the user confirms
with `[y/N]`; non-interactive contexts must pass `--yes-execute`. See
[SECURITY.md](SECURITY.md) for the full whitelist rationale.

## Privacy posture

See [SECURITY.md](SECURITY.md) for the full discussion. In one paragraph:

`ask` never sends template body text by default. `--with-content` is the only
opt-in for that, and in non-interactive environments it requires explicit
consent (`--yes-send` or `NDA_VAULT_NO_CONFIRM=1`). The CLI does not log what
was sent — privacy tooling should not log the things it's protecting.
