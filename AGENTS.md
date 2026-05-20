# AGENTS.md — template-vault-cli

Agent quickstart for `template-vault-cli`, the **storage layer** of the
[contract-ops CLI suite](https://cli.drbaher.com). It stores legal-document
templates (and individual clauses) as plain files in a Git repo, with
provenance, and emits structured JSON the other suite tools consume. It
**structures** existing templates; it does **not** generate clause text.

Installed command: `template-vault` (PyPI package `template-vault-cli`).

## Discover the surface — don't hardcode it

Call these at startup instead of parsing `--help`:

```bash
template-vault --catalog json          # full command + flag inventory (this contract)
template-vault find "<query>" --json   # search results
template-vault info <category>/<name> --json   # one template's metadata + clauses
template-vault list --json             # everything in the vault
template-vault history <ref> --json    # versions + swaps + amends timeline
template-vault stats --json            # vault dashboard
```

The JSON outputs are validated against committed JSON Schemas (JSON Schema
2020-12) under [`docs/spec/`](docs/spec/) — `meta`, `vault-config`,
`info-json`, `find-json`, `history-json`, `stats-json`. They are **stable since
v0.4.8**: a backward-incompatible change requires a major version bump. Validate
against the schema rather than trusting field shapes by convention.

## Output contract

- **stdout** carries the result. With `--json` (on `find` / `info` / `list` /
  `history` / `stats`) it's a single JSON document; otherwise it's human text.
- **stderr** carries diagnostics. Write-side commands (`compose`, `swap`,
  `upgrade`, `import`, `export`) accept `--why` for a short structured
  explanation, printed to stderr so it never pollutes structured stdout.
- Color auto-detects TTY and honors [`NO_COLOR`](https://no-color.org/) and a
  global `--no-color`. `-q` / `--silent` suppress chatter.

## Exit codes

`template-vault` does **not** use the suite's common `0/2/3/4` scheme — branch
on these:

| code | meaning |
|---|---|
| `0` | success |
| `1` | a check reported problems — `verify` found drift, `doctor` found issues, etc. (the command ran fine; the *content* failed the check) |
| `2` | invalid usage (argparse) or an operation error (`VaultError`: bad ref, missing template, write failure, refused LLM send, …) |

(See the cross-suite exit-code matrix at <https://cli.drbaher.com/built-for-agents/> — meanings differ per CLI.)

## Where it fits / the handoff

template-vault is step 0 of the pipeline. Resolve a versioned template and hand
its path to [draft-cli](https://github.com/DrBaher/draft-cli):

```bash
ref=$(template-vault find "mutual nda california" --json | jq -r '.results[0].ref')
template-vault get "$ref" --path-only        # → /path/to/version.md  (for draft-cli)
template-vault get "$ref"                     # → streams the template body to stdout
```

Compose-and-swap with recorded provenance:

```bash
template-vault compose --base nda/house --as nda/house-startup
template-vault swap nda/house-startup --clause "Term and Survival" --from nda/yc
template-vault info nda/house-startup --json   # clause_overrides records what came from where
template-vault upgrade nda/house-startup        # pull parent improvements, keep your swaps
```

## LLM (`ask`) — opt-in, metadata-only by default

`template-vault ask "<query>"` sends **only** template metadata (name, category,
jurisdiction, tags, summary, clause titles) to the configured provider. `--with-content`
adds short excerpts and requires explicit consent — in CI you must pass `--yes-send`
(or set `NDA_VAULT_NO_CONFIRM=1`), otherwise it refuses. Provider config is the
suite-shared `~/.config/contract-ops/llm.json` (CLI flags > `NDA_VAULT_LLM_*` env >
that file > legacy per-CLI files). `ask --json --quiet` gives JSON-only stdout;
`ask --execute` runs an LLM-emitted compose/swap (gated by `--yes-execute`).

## Failure → recovery

| symptom | recover |
|---|---|
| exit `2`, "not a vault" / ref errors | run `template-vault init` first; check the ref with `template-vault list --json` |
| exit `2`, refused LLM send | pass `--yes-send` (or set `NDA_VAULT_NO_CONFIRM=1`) for `--with-content` in non-interactive runs |
| exit `1` from `verify` | a template file drifted from its recorded hash — inspect, then `verify --update-hashes` to re-baseline |
| missing provider key for `ask` | write `~/.config/contract-ops/llm.json` or set `NDA_VAULT_LLM_API_KEY` |

## More

- Cross-CLI interop contract & shared conventions: [`docs/INTEROP.md`](docs/INTEROP.md).
- Architecture, clause-detection regex, storage layout: [`ARCHITECTURE.md`](ARCHITECTURE.md).
- The vault is a Git repo: `template-vault sync` = `git pull`, `template-vault publish` = `git push`.
