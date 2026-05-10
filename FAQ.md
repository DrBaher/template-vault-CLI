# FAQ

## Why Git?

Three reasons.

**Sync is solved.** Multi-user, multi-device, audit log, branching, history,
rollback, blame — the entire substrate that a custom backend would have to
re-invent. You already pay for it via GitHub/GitLab/internal-Git; adding a
vault is one more repo.

**No infrastructure.** No database to back up, no service to monitor, no
auth model to design. The vault is files. `find` walks the directory tree;
`get` opens a file. The whole CLI is one stdlib-only Python file.

**Plain-text reviewability.** A pull request showing the unified diff of a
clause change is the right artifact for legal-team review. Git already
handles the "show me what this commit changes" question better than any
custom UI.

## Why not a database?

A database would let `find` use proper full-text search and let `meta.json`
queries scale to tens of thousands of templates. We don't need that — a
realistic in-house library is a few dozen to a few hundred templates, and
walking that with stdlib is fast (< 50ms in our test fixtures).

The cost of a database is real: you'd need a migration story, a backup story,
a service to run, and a way to keep the database in sync with whatever Git
repo the team checks the templates into. You'd end up with a synchronization
problem you don't have today.

## Can I share my vault publicly?

Yes — point it at a public Git remote. The `import` registry already shares
public templates this way (Common Paper, YC SAFE, Bonterms, etc.), so the
pattern is the same.

For a private vault, point at a private remote. The CLI doesn't care.

## Does `ask` send my templates to OpenAI / Anthropic / etc.?

**No, by default.** `ask` sends only metadata: name, category, jurisdiction,
tags, summary, and clause **titles** — not clause bodies, not template
content.

You can opt in to sending short excerpts (~500 chars per candidate) with
`--with-content`. In an interactive session you'll see a confirmation prompt
naming the provider before anything is sent. In CI, the CLI refuses without
explicit consent (`--yes-send` or `NDA_VAULT_NO_CONFIRM=1`).

If you'd rather not use a hosted LLM at all, point the CLI at a local Ollama
or LM Studio endpoint (`provider: openai`, `base_url: http://localhost:11434/v1`).

## How is this different from asking an LLM to merge my templates?

Three things an LLM workflow can't give you on its own:

1. **Provenance.** `clause_overrides[]` records exactly which clause came from
   which source template at which version, with a timestamp. Months later you
   can answer "where did this carve-out come from?" in one `info` call.
2. **Parent-update tracking.** `forked_at_parent_version` makes `upgrade`
   safe: the next time the parent template gains a v2, `upgrade` shows you
   the per-clause diff and lets you accept improvements without losing your
   locally-swapped clauses. An LLM doesn't have stable memory of what your
   fork started from.
3. **Zero-LLM workflows.** `compose`, `swap`, `upgrade`, `clause-library`
   all work without ever calling an LLM. The output is deterministic; the
   same input produces the same diff. LLM augmentation (`ask`) is one input
   mode for picking which primitives to run, not a requirement.

The shorter version: an LLM can recommend a swap; only the CLI can record
*that you made it* in a way that survives the next conversation.

## Will this work with Word docs?

The vault stores any extension. `upload my.docx --category msa --name x`
writes `msa/x/v1.docx`. But the **clause-aware** features (`clauses`,
`compose`, `swap`, `compare-clauses`, `upgrade`, `clause-library`) read
H2 headers from a text file. If your templates are `.docx`, you'll want to
keep a `.md` companion (or convert via `docx2pdf-cli` and back) for the
clause primitives. Other commands (`upload`, `list`, `find`, `get`, `diff`,
`info`, `import`, `sync`, `publish`, `doctor`) work on any extension.

## Why "clause-aware" instead of "AI-powered"?

Because the differentiator is structural, not generative. The CLI knows
where clauses begin and end, knows their lineage, and can move them around
deterministically. An LLM is welcome to participate by recommending which
clauses to move, but the moves themselves are recorded in `meta.json` and
reproducible without an LLM.

This is also a privacy decision: an LLM-only workflow forces you to send
template bodies to a third party for every operation. A structural workflow
keeps the deterministic 95% local.

## What's the relationship to nda-review-cli?

`nda-review-cli` reviews and negotiates NDAs against a house policy.
`template-vault-cli` stores and composes the templates `nda-review-cli`
draws from. Future integration:

```bash
nda-review-cli draft --template-name nda/house-mutual
```

… would call `template-vault get nda/house-mutual` under the hood if a vault
is configured. Today this isn't wired up — the integration is one-way and
documented as future work.

## Does it support encrypted vaults?

The vault is files in a Git repo. Use `git-crypt`, `git-secret`, your
filesystem encryption, or your repo host's at-rest encryption. The CLI
deliberately stays out of that layer.

## Can I run my own public-source registry?

Right now the registry is bundled in `config/default-sources.json`. If you
want a private registry pointing at internal sources, fork the CLI and edit
that file — it's small. A v0.2 will likely add a registry-override mechanism
(e.g. `--sources path/to/sources.json`), tracked in CHANGELOG.

## Why stdlib-only?

It's a habit shared with the rest of the suite. Stdlib-only means no supply-
chain risk from PyPI dependencies, faster `pip install`, and a CLI that runs
on any Python 3.9+ without a venv. The cost is writing a few things by hand
(HTTP via `urllib`, JSON config, fuzzy matching via `difflib`) instead of
pulling `requests`/`pyyaml`/`rapidfuzz`. For a tool this small, the trade is
worth it.
