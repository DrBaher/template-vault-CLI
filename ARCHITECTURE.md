# Architecture

## Storage model

The vault is a **plain Git repository**. There is no database, no daemon, no
SaaS. Multi-user sync is whatever Git remote you already use.

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
  "clause_overrides": []
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

### Title normalization

For matching by title (in `swap`, `compare-clauses`, `upgrade`), titles are
case-insensitively compared after stripping a leading number prefix:

```
"## 4. Term and Survival"   → "Term and Survival"
"## 4) Term and Survival"   → "Term and Survival"
"## Term and Survival"      → "Term and Survival"
```

A swap that names `"Term and Survival"` matches all three header styles.

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

`ask` does **not** auto-execute LLM-suggested commands. The LLM emits literal
`template-vault swap …` strings; the user copies them into a shell. This keeps
the loop deterministic and reviewable, and it means an LLM hallucination
becomes an obvious "command not found" rather than a corrupted template.

## Privacy posture

See [SECURITY.md](SECURITY.md) for the full discussion. In one paragraph:

`ask` never sends template body text by default. `--with-content` is the only
opt-in for that, and in non-interactive environments it requires explicit
consent (`--yes-send` or `NDA_VAULT_NO_CONFIRM=1`). The CLI does not log what
was sent — privacy tooling should not log the things it's protecting.
