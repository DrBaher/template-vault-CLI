# Cross-CLI interop contract

This document is the **citation point** for what `template-vault-cli` provides
to the rest of the contract-operations CLI suite, and the conventions all
sibling CLIs are expected to share. It exists so sibling repos
([draft-cli](https://github.com/DrBaher/draft-cli),
[nda-review-cli](https://github.com/DrBaher/nda-review-cli),
[compare-cli](https://github.com/DrBaher/compare-cli),
[docx2pdf-cli](https://github.com/DrBaher/docx2pdf-cli),
[sign-cli](https://github.com/DrBaher/sign-cli)) can link here once instead
of reverse-engineering this repo's contracts every time.

The suite is a **convention family**, not a code family. Each CLI is
independently implemented (Python or Node, stdlib-only or minimal-deps).
What's shared:

1. **Schemas** for the data contracts at the boundaries (this doc).
2. **UX conventions** for flags, output streams, and configuration (this doc).
3. **One actually-shared file**: the LLM provider config (next section).

There is **no** shared library, no vendored modules, and intentionally so.

## Shared LLM config

The two Python CLIs (`template-vault-cli` and `nda-review-cli`) share the
same on-disk LLM provider config. Lookup order (`_load_llm_config` in this
repo):

```
~/.config/contract-ops/llm.json        # NEW: suite-wide (suite tools should prefer this)
~/.config/nda-review-cli/llm.json      # legacy: original nda-review-cli location
~/.config/template-vault-cli/llm.json  # legacy: this repo's location
./config/llm.json                       # repo-local override
```

Schema (matches `config/llm.json.example`):

```json
{
  "provider":  "anthropic | openai",
  "model":     "claude-sonnet-4-6 | gpt-4o-mini | ...",
  "api_key":   "sk-...",
  "base_url":  "https://api.example.test/v1/  (openai-compatible only)"
}
```

A user who configures `~/.config/contract-ops/llm.json` once gets working
LLM features across every suite tool that opts into the same lookup order.
Sibling Python CLIs that adopt this lookup get the feature for free; Node
CLIs can read the same file via standard JSON I/O.

## Schemas this repo ships

All under [`docs/spec/`](spec/). JSON Schema 2020-12.

| File | What | Stable since |
|---|---|---|
| [`meta.schema.json`](spec/meta.schema.json) | Per-template `meta.json` | v0.4.8 |
| [`vault-config.schema.json`](spec/vault-config.schema.json) | Top-level `.vault.json` | v0.4.8 |
| [`info-json.schema.json`](spec/info-json.schema.json) | `template-vault info <ref> --json` output | v0.4.8 |
| [`find-json.schema.json`](spec/find-json.schema.json) | `template-vault find <query> --json` output | v0.4.8 |
| [`history-json.schema.json`](spec/history-json.schema.json) | `template-vault history <ref> --json` output | v0.4.8 |
| [`stats-json.schema.json`](spec/stats-json.schema.json) | `template-vault stats --json` output | v0.4.8 |

Downstream tools that consume these outputs (e.g., `nda-review-cli` pulling
clause structure via `info --json`) can validate against these schemas
instead of trusting field shapes by convention.

We commit to **semver-meaningful changes** to these schemas: a backward-
incompatible change (renaming/removing a field, narrowing a type) requires
a major version bump of this CLI. New optional fields are minor-version
additions.

## Schemas this repo DOESN'T ship

These belong in the producing repo or in a future neutral `contract-ops-specs`
repo:

- **`policy.schema.json`** — the `nda-review-cli` policy file format. Lives
  in `nda-review-cli`. Bilingual keyword catalog + preferred-language map per
  clause.
- **`clause-detection-rule.md`** — the four-tier cascade (H2 → bold-numbered
  → ALL-CAPS → synthetic). Currently lives at
  [`compare-cli/docs/clause-detection.md`](https://github.com/DrBaher/compare-cli/blob/main/docs/clause-detection.md).
  This repo's divergences from that spec are documented in
  [`docs/clause-detection-divergence.md`](clause-detection-divergence.md).

A future `drbaher/contract-ops-specs` repo would be the right home for
specs that span multiple CLIs. Not in scope for this round.

## UX conventions across the suite

These are convention-shared (not code-shared); each CLI implements them
independently. Audited and aligned in v0.4.6 / v0.4.7.

### Streams

| Output | Stream |
|---|---|
| Primary command result (`Composed:`, `Swapped`, JSON payload) | **stdout** |
| `--why` explanation block | **stderr** |
| Errors (`error: ...`) | **stderr** |
| `--json` payload | **stdout**, never mixed with prose |
| Progress / diagnostics | **stderr** |

Rule of thumb: stdout is for callers that pipe; stderr is for humans.
Mixing the two breaks `jq` and friends.

### Flags

| Flag | Shape | Notes |
|---|---|---|
| `--help`, `-h` | argparse / commander default | Every CLI |
| `--version`, `-V` | Prints `<cli-name> X.Y.Z` | Every CLI |
| `--json` | Switch output to JSON | Required for any command with a `--json` mode |
| `--why` | Structured explanation on stderr | See "--why envelope" below |
| `--quiet`, `--silent`, `-q` | Suppress non-error output | All three are aliases |
| `--no-color` | Disable ANSI codes (global flag) | Also respects `NO_COLOR` and `FORCE_COLOR` env vars per https://no-color.org/ |
| `--dry-run` | Show plan without writing | Where applicable |
| `--demo` (or `demo` subcommand) | Zero-config first-experience | Each CLI ships one |

### `--why` envelope

Block printed when `--why` is set. Two formats are common in the suite:

**Plain-text (this repo, draft-cli):**

```
[why] <header>
  <line 1>
  <line 2>
  ...
```

**Key=value (compare-cli):**

```
why detection_tier=h2 alignment=ordered-titles classes=12 strict=true exit=0
```

Both go to stderr. Either is acceptable. Plain-text is friendlier for
humans; key=value is friendlier for `awk`-style parsing. Pick one per CLI
and stick with it.

### Color

Auto-detect TTY for stdout. Disable when piping or when `NO_COLOR` is set.
Enable when `FORCE_COLOR` is set. ANSI codes only; no Windows-specific
fallbacks (Windows Terminal handles ANSI fine).

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Generic failure / one or more findings (`doctor` issues, `verify` mismatches, `compare` drift, etc.) |
| 2 | Bad usage (argparse-default) |

Where a command has multiple severity levels (`compare-cli`'s strict
modes, `doctor`'s `--strict` warnings), the higher severity gets exit 1;
default behavior gates only on hard failures.

## Suite-chain framing in READMEs

Every CLI's README header should include the canonical 4-CLI pipeline:

```
draft → review → convert → sign
```

with the current tool bolded. Auxiliary tools (`compare-cli`,
`template-vault-cli`) are noted **separately** — they're not steps in the
linear chain.

Example (from this repo's README header):

> Part of the contract-operations CLI suite. **template-vault-cli** is the
> storage layer feeding the pre-execution pipeline:
> [**draft-cli**](...) (fill placeholders) →
> [**nda-review-cli**](...) (review, redline, negotiate) →
> [**docx2pdf-cli**](...) (DOCX → PDF) →
> [**sign-cli**](...) (signing + audit).
> Cross-version drift detection via [**compare-cli**](...).
> [Showcase site](https://cli.drbaher.com/).

Sibling repos should adopt the same shape (current tool bolded, others
linked).

## Things siblings can adopt at their own pace

Backward-compatible additions any sibling CLI can take without a major bump:

1. **`~/.config/contract-ops/llm.json` first in the LLM-config lookup chain.**
   ~5 LoC change. Users on the new path get suite-wide config; users on the
   old paths keep working.
2. **JSON Schema validation** of `template-vault`-produced outputs they
   already consume. ~20 LoC; gives them an early-warning system if this repo
   accidentally breaks the contract.
3. **`-V` short flag** for `--version` (template-vault adopted in v0.4.7).
4. **`--why` to stderr** if not already.
5. **`-q` / `--silent` aliases** alongside `--quiet`.
6. **Suite-chain framing** that lists all relevant siblings (in particular
   referring to `template-vault-cli` as the storage layer, and `compare-cli`
   as the auxiliary drift gate).

## Things that should move to a neutral spec repo eventually

When the cross-cutting concerns grow to ~3-4 specs, hoist them to
`drbaher/contract-ops-specs`:

- The clause-detection rule (`compare-cli/docs/clause-detection.md`)
- The policy file schema (`nda-review-cli`)
- This INTEROP doc itself
- A formal `--why` envelope spec

Until then, the schemas in this repo are the source of truth for the data
contracts that originate here, and the sibling repos own the contracts that
originate there.
