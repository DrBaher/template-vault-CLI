# Security

## Threat model

The vault holds confidential legal templates. The realistic concerns are:

| Concern | Who | Mitigation |
|---|---|---|
| Vault contents leaked to a third-party LLM provider | LLM API call from `ask` | Default sends metadata only. `--with-content` requires explicit consent. |
| Vault repo accidentally pushed to a public remote | Git misconfiguration | `template-vault publish` is a thin `git push` wrapper — it inherits whatever remote you've configured. The CLI does not default to any remote; you choose. |
| Sensitive content in `--summary` field | User error | The `summary` field is sent to the LLM by default. Don't put privileged content in it. |
| Imported template's hash mismatches the registry | Upstream tampering or registry rot | `import` verifies against the registry's `sha256` if present and aborts on mismatch. `--no-verify` is opt-in. `--pin-hash` records the observed hash on first fetch. |
| Vault disclosed via wider Git access | Org permissions | Treat the vault repo's access controls like any code repo. `template-vault doctor` does not change permissions. |

The CLI does **not** include telemetry, analytics, crash reporting, or any
phone-home behavior. The only outbound network calls are:

1. `import <source-id>` — fetches from the URL in the registry.
2. `ask` — calls the configured LLM endpoint.
3. `sync` / `publish` — invoke `git`.

There are no other callouts.

## What `ask` sends, exactly

### Default (no `--with-content`)

For each of the top-K candidates, the LLM sees:

- `category/name@version`
- `summary`
- `jurisdiction`
- `tags`
- list of clause **titles** (no clause bodies)

Plus the user query and a system prompt.

### With `--with-content`

In addition to the above, for each candidate:

- the first ~500 characters of the template, with newlines flattened to spaces.

Note that "first 500 chars" is a per-candidate cap; a top-K of 5 means up to
~2.5 KB of template text is sent.

### Consent UX

| Context | Behavior |
|---|---|
| Interactive TTY, no `--yes-send`, no `NDA_VAULT_NO_CONFIRM` | Print a warning naming the provider/model/base_url. Prompt `Proceed? [y/N]`. Abort on `n`. |
| `--yes-send` or `NDA_VAULT_NO_CONFIRM=1` | Skip the prompt. |
| Non-interactive (no TTY) without explicit consent | Refuse with a clear error: pass `--yes-send` or set the env var. |

### Logging

The CLI prints what it's about to send (the provider/model identity), but does
**not** log the listing or excerpt contents themselves. Privacy tooling
should not log the things it's protecting.

## `ask --execute` posture

`--execute` parses the LLM response for lines beginning with
`template-vault `, splits them with `shlex`, and runs the ones whose
subcommand is in a hard-coded whitelist: **`compose` and `swap` only**.
Everything else is skipped with a notice — including `upload`, `import`,
`publish`, `sync`, and `ask` itself. This bounds the blast radius of an
LLM hallucination to in-vault structural moves; it cannot upload new
content, push to remotes, or import from URLs.

The chain stops on the first non-zero exit. If the LLM hallucinates a
clause that doesn't exist in the named source, `swap` fails fast with the
list of available clauses (deterministic CLI behavior, not LLM-side
validation), the chain stops, and nothing further runs.

In non-interactive contexts `--execute` requires `--yes-execute` — same
posture as `--with-content`.

## Source-import verification

The bundled registry (`config/default-sources.json`) ships with `sha256: null`
for each entry — we don't pre-pin hashes against URLs we don't control. On
first fetch the CLI:

- Reports the observed hash to stderr.
- Writes the template if you didn't pass `--no-verify`.
- Records the hash to `pinned_source_hashes` in your vault config if you
  passed `--pin-hash`.

On subsequent fetches with a non-null `sha256` (whether bundled or pinned), a
mismatch aborts the import and surfaces the expected vs. observed hash.

If you operate a vault where importing from an upstream that has changed
silently is unacceptable, run `import --pin-hash` once per source after
reviewing the content.

## License compliance

`info` surfaces each template's `license` and (where applicable)
`attribution` fields. Public sources fetched via `import` carry their
upstream license forward. The CLI does not enforce attribution — it's your
responsibility to honor each source's license terms when distributing.

The CLI itself is MIT-licensed.

## Reporting a vulnerability

Open an issue at https://github.com/DrBaher/template-vault-cli/issues with
the `security` label, or email the project owner. We aim to acknowledge
within five business days.
