# Changelog

All notable changes to this project will be documented in this file. The
format is loosely based on [Keep a Changelog](https://keepachangelog.com/),
and the project adheres to semantic versioning once it leaves 0.x.

## Unreleased

### Added
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
