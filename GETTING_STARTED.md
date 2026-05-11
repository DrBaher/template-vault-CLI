# Getting started

Five small scenarios that cover the way real teams adopt `template-vault-cli`.
Run them top-to-bottom or skip to the one that matches your situation.

If you haven't yet, install the CLI first:

```bash
pipx install template-vault-cli                 # recommended
# or `pip install template-vault-cli`, or `pip install 'template-vault-cli[docx]'`
```

See the [README](README.md#install) for the install variants. Everything below
assumes `template-vault --version` works.

---

## 1. Solo founder seeding from public sources

You're a solo founder. You want a small library of well-licensed templates
without writing any of them yourself.

```bash
mkdir my-vault && cd my-vault
template-vault init
template-vault sources                      # see what's available
template-vault import common-paper-mutual-nda
template-vault import yc-safe-post-money-2018
template-vault import bonterms-cloud-terms
template-vault list
```

Each `import` fetches the canonical text from the upstream URL, records the
SHA-256 of what it received, and writes a `meta.json` carrying the upstream
license string and any required attribution. Nothing in this repo bundles
those texts — the CLI is a thin fetch + organize layer.

Now use one:

```bash
template-vault find "vendor diligence"
template-vault get nda/common-paper-mutual > to-send.md
```

---

## 2. In-house team migrating an existing template library

You already have ~30 docs in a shared drive. You want them in the vault with
sensible metadata.

For each existing template:

```bash
template-vault upload ./drive-export/master-services-agreement.docx \
    --category msa \
    --name house-msa \
    --summary "House MSA. Net 30, mutual indemnity, CA venue." \
    --tags house-style,msa,enterprise \
    --jurisdiction California \
    --license private \
    --owner legal-team \
    --uploaded-by "@you"
```

Required fields are prompted for if you skip the flag, except in
`--non-interactive` mode (which fails fast). The `--summary` is the most
important field — it's what powers `find` and what `ask` sends to the LLM.

If you want an LLM-drafted summary you can review before saving:

```bash
template-vault upload ./drive-export/x.md --category nda --name house-mutual \
    --llm-summarize
```

Bulk-loading a directory: write a small shell loop. The CLI is intentionally
single-call so you can compose it however you want.

```bash
for f in drive-export/*.md; do
  name=$(basename "$f" .md)
  template-vault upload "$f" --category nda --name "$name" \
      --summary "imported from drive on $(date +%F)" --non-interactive
done
template-vault doctor   # surface anything missing
```

Commit when you're happy:

```bash
git add . && git commit -m "seed vault from drive export"
template-vault publish     # git push
```

---

## 3. Multi-firm sharing via a Git remote

The vault is just a Git repo. Pick wherever your team already pushes — GitHub,
GitLab, Gitea, an internal Git server — and treat it like any other shared repo.

```bash
git remote add origin git@github.com:our-firm/legal-vault.git
git push -u origin main
```

A teammate clones and is done:

```bash
git clone git@github.com:our-firm/legal-vault.git our-vault
cd our-vault
template-vault list
template-vault sync          # = git pull
```

Multi-user merges work the way they do for any Git repo. We recommend
small commits per upload to minimize merge conflicts on `meta.json`.

---

## 4. Building a derived template through `compose` + `swap`

You have your house mutual NDA. A startup partner wants a friendlier term —
one year of survival instead of three. Instead of editing the file by hand
and losing track, fork it and swap one clause:

```bash
template-vault import common-paper-mutual-nda

template-vault compose \
    --base nda/house-mutual \
    --as   nda/house-mutual-startup

template-vault clauses nda/house-mutual-startup       # which clauses can I swap?
template-vault clauses nda/common-paper-mutual        # which can I borrow from?

template-vault compare-clauses nda/house-mutual nda/common-paper-mutual \
    --clause "Term and Survival"

template-vault swap nda/house-mutual-startup \
    --clause "Term and Survival" \
    --from   nda/common-paper-mutual

template-vault info nda/house-mutual-startup          # see clause_overrides
```

Three months later, your house mutual NDA gets a v2 with a tightened
residuals carve-out. Pull that improvement into your fork — but keep your
locally-swapped Term clause:

```bash
template-vault upgrade nda/house-mutual-startup
# … review per-clause diffs, accept Residuals, decline anything you don't want
```

`upgrade` writes a new version to the derived template (`v2.md`), updates
`forked_at_parent_version`, and leaves swapped clauses untouched.

---

## 5. Asking the LLM for a recommendation

You don't remember which template you have for an enterprise SaaS deal in
California. Ask:

```bash
template-vault ask "which template should I use for enterprise SaaS in California?"
```

By default this sends only **metadata** (name, category, jurisdiction, tags,
summary, clause titles) for the top-K candidates. The LLM recommends a
template and reasoning — referencing the metadata you provided.

If you want the LLM to look at short excerpts of each candidate:

```bash
template-vault ask "which has the strictest survival clause?" --with-content
# In an interactive session you'll see a confirmation prompt naming the
# provider and model before anything is sent.
```

For composition queries, the LLM is instructed to emit `compose` + `swap`
commands using only template names and clause titles from the listing. The
CLI does not currently auto-execute them — you copy-paste into your shell.
This keeps the loop deterministic and reviewable.

Configure the LLM via `~/.config/template-vault-cli/llm.json` (see
`config/llm.json.example`). If you've already configured `nda-review-cli`,
its config is reused so you don't have to set up two providers.
