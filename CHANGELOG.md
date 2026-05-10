# Changelog

All notable changes to this project will be documented in this file. The
format is loosely based on [Keep a Changelog](https://keepachangelog.com/),
and the project adheres to semantic versioning once it leaves 0.x.

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
