# Changelog

All notable changes to this project will be documented in this file. The
format is loosely based on [Keep a Changelog](https://keepachangelog.com/),
and the project adheres to semantic versioning once it leaves 0.x.

## 0.4.3 — 2026-05-19

Quality round: property-based clause-detection tests + clean
`mypy --strict` pass.

### Added
- **Property-based tests** (`tests/test_properties.py`) covering 9
  invariants on `detect_clauses` and `find_clause_by_title`. Each
  property runs ~50 generated cases with deterministic seeds, so
  failures are reproducible. Stdlib-only (no `hypothesis` dep —
  uses `random` + invariant assertions). Tests catch:
  - Cascade priority (T1 > T2 > T3) — H2 doc with injected bold/CAPS
    noise still returns only H2 clauses
  - No clause overlap between adjacent detections
  - `slice_clause_text` round-trips `text[start:end]`
  - `_strip_clause_number` is idempotent
  - Alias resolution symmetry (querying by alias == querying by canonical)
  - Exact-match-beats-substring in `find_clause_by_title`
  - T2 fallback never activates when T1 fires; T3 never activates when
    T2 fires
- **`mypy --strict` clean pass.** The codebase had partial type hints;
  this round closes the gap. 10 small fixes: cast `json.loads`
  returns where they feed typed dicts, parameterize bare `set` /
  `subprocess.CompletedProcess` annotations, fix one shadowed
  exception variable in `cmd_doctor`. Also added an explicit guard
  in `cmd_upgrade` for the case where `derived_from` is set but
  `forked_at_parent_version` isn't (was an `Optional[str]` reaching
  a `str` parameter; now an explicit error with a doctor hint).
- **`make typecheck`** runs `mypy --strict` against
  `template_vault_cli.py`. Lazy-installs mypy on first run.
- **New CI job** (`typecheck`) runs `mypy --strict` on every push and
  PR. Matrix unchanged (Ubuntu × macOS × Python 3.9-3.12 still on
  `unittest`); the new typecheck job runs once on Ubuntu Python 3.12.
- `mypy>=1.10` added to the `[project.optional-dependencies] dev`
  extra alongside `coverage>=7.0`.

### Fixed
- Subtle exception-variable shadow in `cmd_doctor`: an `except VaultError
  as e:` was followed by a `for e in errs:` loop that re-used the same
  name. Python deletes the exception binding after the except block, but
  the reuse was confusing and mypy flagged it. Renamed the loop variable
  to `msg` and the second except's binding to `exc`.

### Stats
Tests: 202 → **215** (+13). Coverage still 87%. `mypy --strict`: clean.

## 0.4.2 — 2026-05-19

Polish round: long-tail coverage tests, a new `stats` command,
`doctor` quality warnings, and three FAQ entries that close obvious
documentation gaps.

### Added
- **`template-vault stats`** — single-screen vault dashboard:
  category counts, version totals, import / composition counts,
  coverage of summaries / tags / sha256, last-activity timestamp.
  `--json` for scripts. Reuses `iter_templates`; no new schema.
- **`doctor` quality warnings** — beyond the existing schema checks,
  `doctor` now surfaces hygiene issues that don't break anything but
  degrade UX:
  - Templates with empty `summary` (kills `find` recall, weakens `ask`)
  - Templates with no detected clauses (suggest the explicit `clauses`
    map)
  - Versions without recorded `sha256` (suggest `verify --update-hashes`)
  - Templates never used (`use_count: 0` + `last_used: null` —
    graveyard candidates)
  - `--strict` makes warnings fail the exit code. `--quiet-warnings`
    suppresses them, showing only hard issues.
- **`list --verbose`** — multi-line output with truncated summary and
  metadata bits on dimmed continuation lines.
- **`list --json`** — structured results, matching the pattern from
  `info --json` / `find --json` / `ask --json`.
- **Global `--no-color`** — works on any subcommand. Sets `NO_COLOR=1`
  internally before argparse runs.
- Three new FAQ entries: "How do I migrate from a folder of `.docx`
  files?", "Can I use it offline?", "How is this different from
  `git submodule`?".
- New GETTING_STARTED scenario 6: integrity-drift detection workflow
  (verify + doctor + stats).

### Changed
- `doctor`'s output adds a `Quality warnings:` section after the
  existing `Issues` listing. Backward compatible: clean vaults still
  print `Status: OK` and exit 0.

### Stats
Tests: 167 → **202** (+35). Coverage 83% → **~87%** on
`template_vault_cli.py` (added long-tail tests for `_llm_request`
both providers, `cmd_init` failure paths, `cmd_sync`/`cmd_publish` git
wrappers, `cmd_import` edge cases, `cmd_upload` flag combinations,
`cmd_verify --strict` paths, list `--json`/`--verbose`, global
`--no-color`).

## 0.4.1 — 2026-05-17

Small alignment patch against
[compare-cli's clause-detection.md spec v1.0](https://github.com/DrBaher/compare-cli/blob/main/docs/clause-detection.md),
plus suite cross-referencing updates. No new commands; no migration
required.

### Changed
- **ALL-CAPS heading detection** now accepts 3-character lines (was 4)
  to match the spec. The blank-line-frame requirement and the
  no-leading-`[` exclusion stay (template-vault is intentionally
  stricter on T3 to avoid false positives in real-world prose). Single-
  token ALL-CAPS lines additionally need ≥ 4 ASCII letters (so `TER` is
  still rejected; `TERM` qualifies; `IP RIGHTS` qualifies as multi-token).
- **`[BRACKETED]` lines** can no longer accidentally match ALL-CAPS
  detection. The regex already required `[A-Z]` as the first character,
  but tests now lock the behavior.

### Added
- New reference doc
  [docs/clause-detection-divergence.md](docs/clause-detection-divergence.md)
  enumerating all 10 divergences between this repo's implementation and
  the compare-cli spec, with recommended direction for each
  (align here / align there / accept divergence).
- README, FAQ, and ARCHITECTURE.md now cross-reference the full
  contract-operations CLI suite at [cli.drbaher.com](https://cli.drbaher.com):
  template-vault → draft → review → compare → convert → sign. Adds
  draft-cli and compare-cli to the suite listing (both shipped after
  v0.4.0).

### Stats
Tests: 164 → **167** (+3). Coverage unchanged at ~83%.

## 0.4.0 — 2026-05-11

Distribution + ergonomics + tooling round. Closes the install loop
(PyPI), adds four new commands, and brings the CLI in line with the
sibling-suite conventions (`--why`, color, completion).

### Added
- **PyPI publish workflow** (`.github/workflows/publish.yml`). Runs on
  `git tag v*` push and uses PyPI Trusted Publishing (no token in
  secrets). One-time setup: configure the project at
  https://pypi.org/manage/account/publishing/ pointing at this repo +
  the `publish.yml` workflow + an environment named `pypi`. After
  that, every `v*.*.*` tag publishes automatically.
- **`template-vault find --json`** — structured search results for
  programmatic consumers. Same shape pattern as `info --json` and
  `ask --json`.
- **`template-vault history <ref>`** — friendly chronological
  timeline of versions, swaps, and amends. `--json` for structured
  output.
- **`template-vault verify`** — content-level sha256 integrity check
  beyond what `doctor` does. Walks every template, computes the hash
  of each version file, compares against the recorded `sha256` on
  the version entry. `--update-hashes` populates missing hashes on
  first adoption. `--strict` treats missing-hash as failure.
- **`template-vault export <ref> --as docx`** — round-trip the .docx
  ingestion. Markdown `#`/`##`/... become Word's `Title`/`Heading 2`/...
  Requires the `[docx]` extra.
- **`--why` flag** on `compose`, `swap`, `upgrade`, `import`, `export`.
  Prints a short structured explanation of what the command did
  (resolved clauses, files touched, meta fields updated). Mirrors the
  `--why` pattern in sibling CLIs.
- **`template-vault completion bash | zsh`** — emit a shell completion
  script for tab-completing subcommands. Hand-rolled, no extra
  dependency. Install with `template-vault completion bash >> ~/.bashrc`.

### Changed
- **Color-aware output**: success/error/warn prefixes (`Created:`,
  `Imported:`, `Composed:`, `Swapped`, `error:`, `note:`) now print
  green/red/yellow when stdout is a TTY. Honors the
  [NO_COLOR convention](https://no-color.org/) for opt-out and
  `FORCE_COLOR` for opt-in. Auto-disables when piping.
- "No such template" error now appends a one-line hint to run
  `template-vault list`.

### Notes
- Test suite: 147 → **164** (+17). Coverage 81% → **83%**.
- The `verify` command introduces a new optional `sha256` field on
  per-version entries in `meta.json`. Backwards compatible: existing
  vaults without recorded hashes work fine; `verify --update-hashes`
  populates them in one shot.

## 0.3.0 — 2026-05-11

Two-round capability lift: detection now handles non-Markdown templates
(bold-numbered, ALL-CAPS, .docx), the alias system became cross-template
and vault-wide, and `upgrade` / `compare-clauses` / `info` gained the
guardrails downstream tools need.

Out-of-scope deliberately: a review/negotiation engine. See
[docs/ROADMAP.md](docs/ROADMAP.md) for a deferred plan to generalize the
nda-review-cli prototype into this repo.

### Added — round 3 (capability lift)

- **Bold-prefix + ALL-CAPS heading fallback** in `detect_clauses`. Runs only
  when H2 detection returns empty — so it can't shadow real H2 sections.
  Catches DOCX-converted templates that use `**1. Purpose**` or
  `CONFIDENTIALITY OBLIGATIONS`. Brings the bulk of real-world legal-team
  source documents into the auto-detected pool.
- **`.docx` ingestion** via `pip install template-vault-cli[docx]`. `upload x.docx`
  converts paragraphs to Markdown using the document's existing heading
  styles (`Heading 1` → `#`, `Heading 2` → `##`, etc.), so H2 detection
  works downstream. Optional dependency — stdlib-only default holds. Without
  the extra, uploading a `.docx` errors with the install hint.
- **`clause-library --suggest-aliases`.** After clustering, surfaces clause
  pairs across templates that have similar bodies but different titles AND
  aren't already aliased. Output is grouped by canonical title pair with
  best-similarity ratio and a list of templates the pair appears in. Pure
  deterministic; no LLM. Closes the "user has to type the alias map by hand"
  gap.
- **Vault-level `template_defaults`** in `.vault.json`. Repository-wide
  defaults (license, owner, jurisdiction, etc.) overlay underneath each
  per-template meta. Per-template values always win. Nothing is ever
  persisted back into the per-template file.
- **Vault-level `clause_aliases`** in `.vault.json`. Repository-wide alias
  map applies to every template; per-template aliases are unioned with
  vault-level for the same canonical title.
- **`info --json`** emits a structured payload (meta + detected clauses +
  resolved aliases + clause overrides). Designed for downstream consumers
  like `nda-review-cli` that need the data without scraping text.
- **`compare-clauses` similarity table** when `--clause` is omitted. Replaces
  the binary `[same]`/`[different]` markers with `[identical]` and `[sim=N.NN]`
  per common clause. Pairing is alias-aware: clauses that have different
  titles but a declared alias appear under one row labelled
  `"Term and Survival / Termination"`.
- **`upload --amend VERSION`.** Overwrites a version file in place rather
  than bumping a new one. Records the prior content's SHA-256 in the
  version's `changelog` for auditability. Destructive — needs `--yes-amend`
  or interactive confirmation.
- **`upgrade --interactive-explain`.** Adds `?` as a third option at the
  per-clause prompt; typing it sends the diff to the configured LLM and
  prints a one-paragraph plain-English explanation, then re-prompts `[y/N]`.
  Opt-in only — sends template content off-device, gated by the flag.

### Changed — round 3
- `iter_templates` now returns `load_meta_resolved` (overlaid) so read-only
  paths (find, list, clause-library, ask listing) get vault-level defaults.
  Mutating commands (swap, upgrade) load raw and use `effective_clause_aliases`
  for matching, so save_meta never persists overlaid values.
- `info` now displays `owner` in the human-readable output.

### Added — round 2
- **Clause aliases.** New `clause_aliases` field in `meta.json` maps a
  canonical clause title to a list of accepted alternate names:
  `{"Term and Survival": ["Termination", "Duration"]}`. `swap`,
  `compare-clauses`, and `upgrade` all resolve aliases. `clause-library`
  builds a vault-wide equivalence union, so two templates that name the
  same clause differently can still cluster together — the cluster output
  annotates non-canonical members `(as 'Termination')`. `doctor` flags
  alias keys that don't match a real detected clause.
- **Wider numbering-prefix support** in clause-title normalization. Now
  strips `(1)`, `[1]`, `1.1` / `1.2.3`, `Article 1.`, `Article IV.`,
  `Section 4.`, `§ 4.`, `Sec. 4.`, `Clause 7.`, `Part II.` — in addition
  to the original `1.` / `1)`.
- `upgrade --dry-run` shows the per-clause diffs that would be applied
  without writing a new derived version or touching `meta.json`.
- `ask --quiet` (only valid with `--json`): suppresses the human-readable
  answer so stdout is JSON-only. Friendlier for shell pipelines.
- `make coverage` target: runs the suite under `coverage.py` (added as an
  optional `dev` extra) and prints a branch-coverage report. Current
  baseline is **80%** line coverage on `template_vault_cli.py`.
- ARCHITECTURE.md gained a "Clause library (cross-template extraction)"
  section and an expanded "Title normalization / aliases" section.
- README.md gained a "Quick tour" section with a verbatim end-to-end
  session transcript.

### Changed
- **`find_clause_by_title` no longer silently picks the first substring
  match when the query is ambiguous.** A query that substring-matches two
  or more distinct clauses now raises `VaultError` listing the candidates
  so the user can disambiguate. Previously, `--clause "term"` against a
  template with both "Term and Survival" and "Termination" would silently
  pick whichever came first; that's now a hard error with a clear message.
- `clause-library` runs its `SequenceMatcher.ratio()` on the clause body
  **without the H2 header line**. Two clauses with identical content but
  different numbering (`## 4. Foo` vs `## 7. Foo`) now cluster correctly.
- Empty-detection error messages on `swap` now hint at the explicit
  `clauses` map in `meta.json` when no H2 headers are detected.
- `ask`'s ARCHITECTURE.md write-up is no longer stale: it now documents
  the v0.2 `--execute` opt-in, the compose/swap whitelist, and the
  chain-stop on failure.

### Fixed
- CI smoke step had no `set -euo pipefail`, so an early failure (e.g.
  broken `template-vault init`) would silently let the job pass as long
  as the last command exited 0. Now bails on the first failure. Also
  `mkdir /tmp/tv-smoke` → `rm -rf … && mkdir -p …` so retries don't fail
  on a stale dir.

## 0.2.0 — 2026-05-10

### Added
- `clause-library --extract` now actually writes the extracted clause files
  to `clauses/<category>/<slug>.md` with a provenance comment naming the
  source templates. New `--yes-extract-all` flag for non-interactive use.
  Without it, `--extract` in a non-tty context refuses with a clear error.
- Custom-registry override for `import` and `sources`: `--sources PATH` flag
  and `NDA_VAULT_SOURCES` env var (CLI flag wins). Lets a team point at an
  internal sources registry without forking the CLI.
- `ask --execute` parses `template-vault compose` / `swap` lines from the
  LLM response and runs them in-process. Whitelist of two subcommands —
  `upload`, `import`, `publish` etc. are skipped with a notice. Interactive
  confirmation by default; `--yes-execute` to skip the prompt.

### Changed
- `iter_templates` now also skips a top-level `clauses/` directory (introduced
  by `clause-library --extract`) so extracted clause files aren't mistaken
  for templates.
- Test suite grew from 94 to 112 tests.

## 0.1.0 — 2026-05-10

Initial release.

### Added
- Vault model: Git-backed plain-file storage with one `meta.json` per template,
  versions in the same directory.
- Storage commands: `init`, `upload`, `list`, `find`, `get`, `info`, `diff`.
- Clause-aware composition primitives: `clauses`, `compose`, `swap`,
  `compare-clauses`, `upgrade`, `clause-library`. Provenance recorded in
  `derived_from`, `forked_at_parent_version`, and `clause_overrides[]`.
- Public-source registry (`sources`, `import`) with optional SHA-256
  hash-pinning. Bundled IDs: Common Paper mutual/one-way NDA, Common Paper
  DPA, YC SAFE pre/post-money 2018, Bonterms cloud terms.
- LLM `ask` with metadata-only default and `--with-content` opt-in. Privacy
  gating: confirmation prompt in interactive mode, refusal in non-interactive
  mode without explicit consent.
- `sync` / `publish` thin wrappers around `git pull` / `git push`.
- `doctor` integrity check.
- 94-test suite (`unittest`, mocked `urllib.request`).

### Notes
- No third-party Python dependencies.
- Texts of public sources are NOT bundled — fetched at `import` time.
