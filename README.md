# template-vault-cli

> A Git-backed, **clause-aware** package manager for legal-document templates.
> Public sources (Common Paper, YC SAFE, Bonterms) and your own house templates,
> in one searchable, composable, version-tracked vault. Stdlib-only Python. MIT.

`template-vault-cli` treats clauses as first-class structural objects. You can
fork a template, swap a single clause from another template into it, and later
pull upstream parent improvements into your fork — with provenance recorded in
`meta.json` rather than guessed by an LLM.

```
pip install template-vault-cli
template-vault init
template-vault import common-paper-mutual-nda
template-vault upload my-house-mutual.md --category nda --name house-mutual
```

## What it does

- **Stores** templates as plain files in a Git repo. Multi-user sync = `git pull` / `git push`.
- **Indexes** them with a small `meta.json` per template: category, jurisdiction, tags, summary.
- **Searches** by category, tag, jurisdiction, or keyword (`find`).
- **Composes** new templates by forking + swapping clauses, with provenance recorded.
- **Upgrades** derived templates when their parents get new versions.
- **Asks** an LLM (Anthropic / OpenAI / OpenAI-compatible) for a recommendation, opt-in,
  metadata-only by default.

The CLI **structures** existing templates. It does **not generate** new clause text.

## The clause-aware composition workflow

```bash
# 1. Fork a parent template
template-vault compose \
    --base nda/house-mutual \
    --as   nda/house-mutual-startup

# 2. Swap one clause from another template
template-vault swap nda/house-mutual-startup \
    --clause "Term and Survival" \
    --from   nda/yc-startup-friendly

# 3. Compare clauses across templates before deciding
template-vault compare-clauses nda/house-mutual nda/common-paper-mutual \
    --clause "Residual Knowledge"

# 4. When the parent gets a new version, pull its improvements in.
#    Clauses you locally swapped are preserved.
template-vault upgrade nda/house-mutual-startup --accept-all

# 5. Find clauses that recur across the vault — candidates for extraction
template-vault clause-library --threshold 0.85
```

Every swap appends to `clause_overrides` in `meta.json`, so you (and `upgrade`)
always know which clauses came from where.

## Command reference

```
template-vault init [--bare] [--path .]
template-vault upload <file>
    --category <cat> --name <slug>
    [--version v3] [--supersedes v2] [--summary "..."]
    [--tags a,b] [--jurisdiction "California,Delaware"]
    [--license MIT] [--llm-summarize]
template-vault list   [--category nda] [--tag house-style] [--jurisdiction California]
template-vault find   "<keyword>"
template-vault get    <category>/<name>[@version] [--path-only]
template-vault info   <category>/<name>
template-vault diff   <category>/<name> <version-a> <version-b>

# Clause-aware composition
template-vault clauses          <category>/<name>
template-vault compose          --base <ref> --as <category>/<new-name>
template-vault swap             <target> --clause "<title>" --from <ref>
template-vault compare-clauses  <a> <b> [--clause "<title>"]
template-vault upgrade          <ref> [--accept-all]
template-vault clause-library   [--threshold 0.85] [--extract]

# LLM (opt-in, metadata-only by default)
template-vault ask "<query>" [--with-content] [--top-k 5] [--llm anthropic]
template-vault ask "<query>" --execute [--yes-execute]   # run LLM-emitted compose/swap

# Public sources
template-vault sources [--sources path/to/internal-sources.json]
template-vault import <source-id> [--no-verify | --pin-hash] [--sources …]

# Sync + housekeeping
template-vault sync          # git pull
template-vault publish       # git push
template-vault doctor        # vault integrity check
```

## Privacy posture

- `ask` sends **only** template metadata (name, category, jurisdiction, tags,
  summary, clause titles) to the LLM by default.
- `--with-content` adds short excerpts. In an interactive session it asks for
  confirmation showing the provider/model. In CI, you must pass `--yes-send` or
  set `NDA_VAULT_NO_CONFIRM=1`. Otherwise it refuses.
- See [SECURITY.md](SECURITY.md) for the full threat model.

## Storage layout

```
your-vault/                                ← a git repo
├── .vault.json                            ← vault config
├── nda/
│   ├── house-mutual/
│   │   ├── v1.md
│   │   ├── v2.md
│   │   ├── v3.md
│   │   └── meta.json
│   └── yc-startup-friendly/
│       ├── v1.md
│       └── meta.json
├── investment/
│   └── safe-post-money/
└── msa/
```

Categories are top-level dirs. Each template is a directory of versioned files
plus exactly one `meta.json`. See [ARCHITECTURE.md](ARCHITECTURE.md) for the
full schema and the clause-detection regex.

## Suite

`template-vault-cli` belongs to a small contract-operations toolkit:

- **[nda-review-cli](https://github.com/DrBaher/nda-review-cli)** — drafts,
  reviews, negotiates NDAs against a house policy.
- **[docx2pdf-cli](https://github.com/DrBaher/docx2pdf-cli)** — DOCX → PDF.
- **[sign-cli](https://github.com/DrBaher/sign-cli)** — multi-provider e-signature
  with hash-chained audit logs.

Future integration: `nda-review-cli draft --template-name <category>/<name>`
will resolve via `template-vault get` if a vault is configured.

## Install

```bash
pipx install template-vault-cli       # recommended
# or
pip install template-vault-cli
```

Requires Python 3.9+. **No third-party runtime dependencies** — stdlib only.

## License

MIT for the code. The CLI fetches public-source templates from upstream URLs
at `import` time and does **not** bundle Common Paper, YC, Bonterms, or any
other party's text.
