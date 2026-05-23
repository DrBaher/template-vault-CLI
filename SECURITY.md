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
| Template name/category escaping the vault dir | Crafted reference, `compose --as`, or a custom sources registry | `category`/`name` are validated as single path segments — a `../../etc/passwd`-style value is rejected, so reads/writes stay inside the vault root. |
| Local file read via a crafted source URL | Malicious/mistyped `--sources` registry | `import` only fetches `http`/`https`; `file://`, `gopher://`, `data:` etc. are refused, so a registry URL can't make the CLI read an arbitrary local file. |
| LLM API key sent in cleartext | Misconfigured `base_url` | The LLM `base_url` must be `https` (or `http://localhost` for a local model). Plain-`http` to a remote host is refused so the key never crosses the wire unencrypted. |

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

### API key handling

- The LLM is **opt-in and off by default** — only `ask` ever uses it, and it
  is not on any hot path (`list`/`find`/`get`/`compose`/`swap`/`info` never
  call out). Without a key, only `ask` errors; everything else works offline.
- The key is read from env (`NDA_VAULT_LLM_API_KEY`) or `llm.json`, placed
  **only** in the request `Authorization`/`x-api-key` header, and is **never**
  printed — not in the consent banner, the `--why` block, or error messages
  (HTTP errors surface status/reason only). It never reaches the vault or git
  history.
- `base_url` is validated before use: `https` only, except `http://localhost`
  (and `127.0.0.1`/`::1`) for local providers like Ollama / LM Studio. This
  prevents the key from being sent to a remote host over an unencrypted
  connection, and blocks non-http(s) schemes.
- **Lock down `llm.json`.** It holds your API key — keep it owner-only:

  ```bash
  chmod 600 ~/.config/contract-ops/llm.json
  ```

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

## Filesystem permissions

The working copy is **plaintext** — templates and metadata on disk are not
encrypted. As defense in depth (POSIX, best-effort):

- A newly created vault directory is `0700` (owner-only).
- `.vault.json`, every `meta.json`, and every template version file are
  written `0600`.

These are no-ops on Windows (rely on NTFS ACLs) and the CLI never silently
re-permissions a directory you already had. They are **not** a substitute for
the real controls:

1. **Full-disk encryption** (FileVault / LUKS / BitLocker) — the primary one.
2. A **private git remote** — never push a template vault to a public repo.
3. `git config commit.gpgsign true` in the vault if you want signed history.

## Supply chain & CI integrity

- **GitHub Actions are pinned to full commit SHAs** (not floating `@v4`-style
  tags), each annotated with the version it resolves to. This matters most in
  `publish.yml`, which holds `id-token: write` (PyPI publishing rights) — a
  repointed floating tag there could otherwise publish a malicious release.
  **Dependabot** (`github-actions`, weekly) keeps the pinned SHAs current.
- **Trusted Publishing + build attestations.** Releases publish via PyPI
  Trusted Publishing (OIDC; no stored token) with PEP 740 `attestations: true`,
  so each artifact carries verifiable build provenance.
- **Static analysis in CI:** **Bandit** (`--severity-level medium`) and
  **CodeQL** (`security-extended`) run on every push/PR — a guard against
  introducing `shell=True`, `eval`, `pickle`, an unvalidated `urlopen`, etc.
  (Low Bandit findings — `B404`/`B603`/`B607` subprocess, `B101` assert — are
  expected noise for a stdlib CLI that shells out to `git`, hence the
  medium-and-above gate.)
- **Least-privilege workflows:** `contents: read` by default; `id-token: write`
  is granted **only** on the publish job, never on the build job.
- **No `shell=True`/`eval`/`exec`/`pickle`/`yaml.load`.** JSON only; all
  subprocess calls are list-form; git invocations don't interpolate untrusted
  shell.

## Recommended repository settings (maintainer toggles — not enforceable from the repo)

These cannot be set from files in the repo; configure them once in GitHub:

- [ ] **Protect the `pypi` deployment environment** (Settings → Environments →
      `pypi` → required reviewers) so a publish needs human approval even if a
      tag is pushed.
- [ ] **Branch protection on `main`:** require a PR, passing CI, and review
      (CODEOWNERS is in `.github/CODEOWNERS`); consider "require signed commits".
- [ ] Enable **code scanning** (Settings → Code security) so CodeQL results
      surface in the Security tab, and turn on **Dependabot alerts**.
- [ ] Confirm the PyPI Trusted Publisher points at this repo + `publish.yml` +
      the `pypi` environment.

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
