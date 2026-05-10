# Changelog

All notable changes to this project will be documented in this file. The
format is loosely based on [Keep a Changelog](https://keepachangelog.com/),
and the project adheres to semantic versioning once it leaves 0.x.

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
