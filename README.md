# template-vault-cli

> A Git-backed, **clause-aware** package manager for legal-document templates.
> Public sources (Common Paper, YC SAFE, Bonterms) and your own house templates,
> in one searchable, composable, version-tracked vault. Stdlib-only Python. MIT.

**Why it's different from a folder of `.docx` files:** the CLI treats clauses
as first-class structural objects with provenance. You can fork a template,
swap a single clause from another template into it, and later pull upstream
parent improvements into your fork — `meta.json` records which clauses came
from where, so the merge is deterministic. An LLM can recommend
compose/swap; the execution stays rule-based and reproducible without one.

## Install

```bash
pipx install template-vault-cli                 # recommended
# or
pip install template-vault-cli                  # stdlib-only, no isolation
pip install 'template-vault-cli[docx]'          # +.docx ingestion (python-docx)
```

Python 3.9+. **No third-party runtime dependencies** in the default install —
`[docx]` adds `python-docx` only when you want to upload `.docx` files.

## 30-second first run

Three commands, zero file authoring — fetches a real public template into a
fresh vault:

```bash
mkdir my-vault && cd my-vault
template-vault init
template-vault import common-paper-mutual-nda
template-vault list
```

You should see one template registered under `nda/`. From there, `find`,
`info`, `clauses`, `compose`, and `swap` all work against it. See the
[end-to-end tour](#end-to-end-clause-aware-composition) below for the
composition workflow.

## What it does

- **Stores** templates as plain files in a Git repo. Multi-user sync = `git pull` / `git push`.
- **Indexes** them with a small `meta.json` per template: category, jurisdiction, tags, summary.
- **Searches** by category, tag, jurisdiction, or keyword (`find`).
- **Composes** new templates by forking + swapping clauses, with provenance recorded.
- **Upgrades** derived templates when their parents get new versions.
- **Asks** an LLM (Anthropic / OpenAI / OpenAI-compatible) for a recommendation, opt-in,
  metadata-only by default.

The CLI **structures** existing templates. It does **not generate** new clause text.

## End-to-end: clause-aware composition

A runnable transcript using inline file content so you can copy-paste the
whole block into a fresh directory:

```bash
mkdir tour && cd tour
template-vault init

cat > house.md <<'EOF'
# House NDA

## Purpose
Evaluate a relationship.

## Term and Survival
Two years from the Effective Date.
EOF

cat > yc.md <<'EOF'
# YC NDA

## Purpose
Exploring.

## Term and Survival
One year from the Effective Date.
EOF

template-vault upload house.md --category nda --name house \
    --summary "house mutual" --non-interactive
template-vault upload yc.md    --category nda --name yc \
    --summary "yc-style"    --non-interactive

# Fork the house NDA and swap one clause from the YC one.
template-vault compose --base nda/house --as nda/house-startup
template-vault swap nda/house-startup --clause "Term and Survival" --from nda/yc
template-vault info nda/house-startup
```

`info` shows `clause_overrides: 1` with the entry `"Term and Survival" from
nda/yc@v1` — that's the provenance. When `nda/house` later gets a `v2`,
`template-vault upgrade nda/house-startup` pulls the parent's other clause
changes in but leaves the locally-swapped Term clause alone. That's the
whole point of recording the override.

For a tour of the public-source pattern, do the same dance but use `import`
instead of authoring files:

```bash
template-vault import common-paper-mutual-nda      # → nda/common-paper-mutual
template-vault import common-paper-one-way-nda     # → nda/common-paper-one-way
template-vault compare-clauses nda/common-paper-mutual nda/common-paper-one-way
```

Every swap appends to `clause_overrides` in `meta.json`. You — and `upgrade`
— always know which clauses came from where.

## Command reference

```
template-vault init [--bare] [--path .]
template-vault upload <file>
    --category <cat> --name <slug>
    [--version v3] [--supersedes v2] [--summary "..."]
    [--tags a,b] [--jurisdiction "California,Delaware"]
    [--license MIT] [--llm-summarize]
    [--amend v3 [--yes-amend]]                      # overwrite a version in place
template-vault list    [--category nda] [--tag house-style] [--jurisdiction California]
template-vault find    "<keyword>" [--top-k 10] [--json]
template-vault get     <category>/<name>[@version] [--path-only]
template-vault info    <category>/<name> [--json]   # --json for scripts
template-vault diff    <category>/<name> <version-a> <version-b>
template-vault history <category>/<name> [--json]   # versions + swaps + amends timeline
template-vault export  <category>/<name> --as docx [--output PATH]   # needs [docx] extra
template-vault verify  [--update-hashes] [--strict]  # content-level sha256 check

# Clause-aware composition
template-vault clauses          <category>/<name>
template-vault compose          --base <ref> --as <category>/<new-name>
template-vault swap             <target> --clause "<title>" --from <ref>
template-vault compare-clauses  <a> <b> [--clause "<title>"]
template-vault upgrade          <ref> [--accept-all] [--dry-run] [--interactive-explain]
template-vault clause-library   [--threshold 0.85] [--extract] [--suggest-aliases]

# LLM (opt-in, metadata-only by default)
template-vault ask "<query>" [--with-content] [--top-k 5] [--llm anthropic]
template-vault ask "<query>" --json [--quiet]            # quiet → JSON-only stdout
template-vault ask "<query>" --execute [--yes-execute]   # run LLM-emitted compose/swap

# Public sources
template-vault sources [--sources path/to/internal-sources.json]
template-vault import <source-id> [--no-verify | --pin-hash] [--sources …]

# Sync + housekeeping
template-vault sync          # git pull
template-vault publish       # git push
template-vault doctor        # vault integrity check (schema-level)
template-vault completion bash | zsh    # emit shell completion script
```

Most write-side commands (`compose`, `swap`, `upgrade`, `import`, `export`)
accept `--why` for a short structured explanation of what they did. Color
output auto-detects TTY; honors the [NO_COLOR](https://no-color.org/)
convention.

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

## License

MIT for the code. The CLI fetches public-source templates from upstream URLs
at `import` time and does **not** bundle Common Paper, YC, Bonterms, or any
other party's text.
