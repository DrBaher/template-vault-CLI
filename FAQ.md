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
H2 headers from a text file. The recommended path: install the `[docx]`
extra (`pip install 'template-vault-cli[docx]'`) and `upload my.docx`
will convert it to Markdown on the way in, preserving `Heading 1` /
`Heading 2` styles as `#` / `##`. The reverse direction works too:
`template-vault export <ref> --as docx` converts a Markdown template
back to Word format. Other commands (`list`, `find`, `get`, `diff`,
`info`, `import`, `sync`, `publish`, `doctor`) work on any extension.

## How do I migrate from a folder of `.docx` files?

Three steps. Assume the files live at `~/legal-drive-export/`:

```bash
mkdir my-vault && cd my-vault
template-vault init

# Install the docx extra (needed for the .docx -> Markdown conversion at upload).
pip install 'template-vault-cli[docx]'

# Bulk upload. Categories come from the source folder structure; you'll
# also want to add summaries for `find`/`ask` recall.
for f in ~/legal-drive-export/nda/*.docx; do
  name=$(basename "$f" .docx)
  template-vault upload "$f" --category nda --name "$name" \
      --summary "imported from drive on $(date +%F)" --non-interactive
done

# Surface the templates that came in without recognized clause structure,
# empty summaries, or missing hashes -- doctor groups all of this into
# "Quality warnings".
template-vault doctor

# Lock content with sha256 so subsequent edits are detectable.
template-vault verify --update-hashes

# Commit + push (the vault is a git repo).
git add . && git commit -m "seed from drive export"
template-vault publish     # = git push
```

If the `.docx` headings aren't structured (no `Heading 1` / `Heading 2`
styles in Word), the bold-numbered and ALL-CAPS fallback detection in
`detect_clauses` will still try; failing that, you can hand-write an
explicit `clauses` map in each `meta.json` (see ARCHITECTURE.md).
`template-vault doctor` flags exactly which templates need it.

## Can I use it offline?

Yes for everything except `import` and `ask`. After `init`, the vault
is just a Git repo of files on your disk; there's nothing to phone
home. Specifically:

- **Works offline**: `init`, `upload`, `list`, `find`, `get`, `info`,
  `diff`, `clauses`, `compose`, `swap`, `compare-clauses`, `upgrade`,
  `clause-library`, `history`, `verify`, `export`, `stats`, `doctor`,
  `sync` and `publish` (those use whatever git remote setup you have,
  which can be local), `sources` (lists the bundled registry — no
  network needed), `completion`.
- **Needs network**: `import` (fetches the upstream template body from
  the URL in the registry), `ask` (sends a request to the configured
  LLM provider).
- **Optional network**: `upgrade --interactive-explain` only contacts
  the LLM when the user types `?` at the prompt.

The CLI doesn't have any telemetry, analytics, or "phone home" calls.

## How is this different from `git submodule`?

Both are git-based and both let you share template files via a remote.
The difference is in the unit of operation. `git submodule` pins a
whole sub-repo at a commit; you bring the entire upstream tree in or
not. This CLI works on individual **templates** and individual
**clauses** within those templates, with provenance recorded in
`meta.json`:

- `template-vault import common-paper-mutual-nda` pulls one specific
  template at one specific version, with its license and SHA-256
  recorded.
- `template-vault compose --base nda/house --as nda/house-startup`
  forks one template and remembers the parent.
- `template-vault swap nda/house-startup --clause "Term and Survival"
  --from nda/yc` substitutes a single clause; the swap is recorded in
  `clause_overrides[]`.
- `template-vault upgrade nda/house-startup` pulls upstream parent
  improvements but preserves locally-swapped clauses — deterministic
  three-way merge at the clause level.

None of this is something `git submodule` can do; submodules are too
coarse-grained. Conversely, if you want to track an entire upstream
template *repository* as a sub-tree, submodules are fine and this CLI
isn't trying to replace them.

## Why "clause-aware" instead of "AI-powered"?

Because the differentiator is structural, not generative. The CLI knows
where clauses begin and end, knows their lineage, and can move them around
deterministically. An LLM is welcome to participate by recommending which
clauses to move, but the moves themselves are recorded in `meta.json` and
reproducible without an LLM.

This is also a privacy decision: an LLM-only workflow forces you to send
template bodies to a third party for every operation. A structural workflow
keeps the deterministic 95% local.

## What's the relationship to the other CLIs in the suite?

`template-vault-cli` is the **storage layer** of the
[contract-ops CLI suite](https://cli.drbaher.com). It feeds the
**pre-execution pipeline** — four tools, run in order:

1. **[draft-cli](https://github.com/DrBaher/draft-cli)** fills placeholders
   in a template (`[Party A]` → `"Acme Corporation"`, etc.).
2. **[nda-review-cli](https://github.com/DrBaher/nda-review-cli)** reviews
   and negotiates against a house policy. Pulls clause structure and
   preferred-language references from a configured vault via
   `template-vault info --json` and `template-vault get`.
3. **[docx2pdf-cli](https://github.com/DrBaher/docx2pdf-cli)** converts the
   agreed draft to a signable PDF.
4. **[sign-cli](https://github.com/DrBaher/sign-cli)** collects signatures
   with hash-chained audit logs.

**Auxiliary:**
[compare-cli](https://github.com/DrBaher/compare-cli) is the clause-aware
drift detector — runs between two versions of a contract (typically the
last-agreed draft vs the about-to-be-signed PDF). Shares the
[clause-detection spec](https://github.com/DrBaher/compare-cli/blob/main/docs/clause-detection.md)
with this repo; see [ARCHITECTURE.md](ARCHITECTURE.md#cross-repo-spec) for
the divergence notes.

All six tools compose via stdin/stdout + deterministic JSON contracts.
Typical pipeline (each step is one of the CLIs):

```
get template → fill placeholders → review → diff vs original → convert → sign
```

A reasonable end-to-end invocation:

```bash
template-vault get nda/house-mutual \
  | draft --params deal-acme.json \
  | nda-review review --file - --policy nda \
  | compare --against /tmp/original.md \
  | docx2pdf - draft-acme.pdf \
  | sign-cli send --signers a@acme.com,b@vendor.com
```

## Does it support encrypted vaults?

The vault is files in a Git repo. Use `git-crypt`, `git-secret`, your
filesystem encryption, or your repo host's at-rest encryption. The CLI
deliberately stays out of that layer.

## Can I run my own public-source registry?

Yes. Two ways:

```bash
# CLI flag, applies to one invocation
template-vault sources --sources ~/internal-sources.json
template-vault import internal-vendor-nda --sources ~/internal-sources.json

# Env var, applies to every invocation in the shell
export NDA_VAULT_SOURCES=~/internal-sources.json
template-vault sources                       # uses your registry
```

The registry file follows the same shape as `config/default-sources.json`.
The CLI flag wins over the env var, which wins over the bundled default.

## Does `ask` actually run the commands it suggests?

Only with `--execute`, and only `compose` / `swap`. Everything else
(`upload`, `import`, `publish`, …) is skipped with a notice — those have
side effects we don't want a hallucinated LLM line touching.

```bash
template-vault ask "compose a startup-friendly NDA from yc and house" --execute
# Shows the parsed commands, asks Run these? [y/N], runs each in-process,
# stops the chain on the first failure.
```

In non-interactive contexts you must pass `--yes-execute` to skip the
confirmation. The chain is still order-preserving and stops on the first
non-zero exit, so a hallucinated clause name fails fast and the rest of the
chain doesn't run.

## Why stdlib-only?

It's a habit shared with the rest of the suite. Stdlib-only means no supply-
chain risk from PyPI dependencies, faster `pip install`, and a CLI that runs
on any Python 3.9+ without a venv. The cost is writing a few things by hand
(HTTP via `urllib`, JSON config, fuzzy matching via `difflib`) instead of
pulling `requests`/`pyyaml`/`rapidfuzz`. For a tool this small, the trade is
worth it.
