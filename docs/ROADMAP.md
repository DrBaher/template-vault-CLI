# Roadmap — review/negotiation engine

This document captures a deferred design from May 2026. **Not currently in
flight.** Read this when you're ready to expand template-vault-CLI from
"template manager" to "legal-document operations CLI: store, compose,
review, and negotiate any agreement type."

## Goal

Generalize the proof-of-concept built in
[nda-review-cli](https://github.com/DrBaher/nda-review-cli) so it works for
any agreement type (NDA, MSA, employment, licensing, DPA, …), and make the
result shareable open-source infrastructure for legal-ops teams.

End state: template-vault-CLI is the canonical tool. `nda-review-cli`
becomes deprecated reference, its ideas folded in and generalized.

## Why this lives in template-vault-CLI (not as a separate tool)

- The vault already has the clause infrastructure (detection, aliases,
  layered config, `info --json`) any review engine needs.
- Policies reference clauses; clauses live here; locality matters.
- One install / one mental model for the legal-ops user.

## Phased plan

Each phase ships something usable. You can stop at any boundary.

### Phase 1 — Foundation (~600-900 LoC, ~5-7 days)

- New `template-vault review --file <doc> --agreement-type <type>` command.
- Policy schema: vault-level + per-category `policies/<type>.json`, layered
  like `clause_aliases`. Reuse the proven shape from
  nda-review-cli's `config/default-policy.json`:
  ```json
  {
    "version": "0.1.0",
    "clause_rules": {
      "<slug>": {
        "keywords": [...],
        "preferred": "...",
        "red_flags": [...],
        "category": "legal|commercial|operational",  // NEW, optional
        "severity": "high|medium|low",               // NEW, optional
        "redline_ref": "nda/house-mutual"            // NEW, optional
      }
    }
  }
  ```
- Document ingestion (`--file` accepts a path; works inside or outside a vault).
- Clause classification using existing `detect_clauses` + the policy's
  keyword catalogue.
- Issue list output: per-clause findings, red-flag matches.
- `--json` for programmatic consumers. Pin `schema_version` from day one.
- 30+ tests.

**Recommended split into two PRs:** schema-only first (~200 LoC), then
engine (~500-700 LoC). Locks the contract before code depends on it.

### Phase 2 — Pilot on Employment (~200-400 LoC + lawyer time)

- Author `policies/employment.json` starter — defensible baseline.
- Smoke against 2-3 sample employment agreements.
- Iterate schema based on what breaks.
- De-risks the schema before porting NDA quality.

### Phase 3 — Port nda-review-cli's NDA quality (~600-900 LoC)

- Bilingual keyword handling (schema supports; engine needs to respect).
- Counterparty profiles (`profiles/<name>.json`, `--learn-profile`).
- Per-agreement-type scoring profiles.
- Generalize `build-playbook` for any agreement type.
- Migration tool: `template-vault import-policy <path> --as-agreement-type nda`
  so existing nda-review-cli users move over without retyping.

### Phase 4 — Parity + deprecation (~1-2 days)

- Run both tools against the same NDA corpus; verify match.
- Cut a milestone release.
- nda-review-cli README → "Deprecated. Use template-vault-cli's `review`."

### Phase 5 — Shareability polish (~1 week)

- `PLAYBOOK_SCHEMA.md` and `POLICY_SCHEMA.md` as stable public contracts.
- Starter policies bundled for: NDA, MSA, employment, licensing, DPA.
- Public-policy registry pattern (like the existing `sources` registry,
  with hash pinning) for community-shared policies.
- README + GETTING_STARTED repositioned for legal-ops audience.

## Caveats to read before starting

- ~600-900 LoC for Phase 1 is real work. ~5-7 focused days, not an afternoon.
- The lawyer-content work in Phase 2 is the limiting factor, not engineering.
  A defensible employment policy is several subject-matter hours per draft.
- Phase 3 has privacy implications. Counterparty profiles store inferences
  about how third parties negotiate. Think through defaults: opt-in,
  per-counterparty redaction, retention policy.
- Don't deprecate nda-review-cli until Phase 4 parity is verified against
  a real NDA corpus.
- Policies need to be community-curatable. Treat the policy file format as
  a stable public schema from the first release; bumping it later is
  expensive.

## Open questions

- Single `policies/` directory or per-category nesting?
- Where do counterparty profiles live — `.vault.json`, separate dir, or
  outside the vault (since they're sensitive)?
- Should `redline_ref` point at a template or at a specific clause within a
  template? (Probably the latter: `nda/house-mutual#term-and-survival`.)
- How does this interact with the existing `ask --execute` flow?
  Probably: `review` produces structured recommendations; `ask --execute`
  acts on them. They compose.

## What to read first when you come back

1. `nda-review-cli/config/default-policy.json` — the schema this builds on.
2. `nda-review-cli/ARCHITECTURE.md` — the review pipeline shape.
3. `nda-review-cli/rule_engine.py` — the regex catalogue / matcher.
4. This repo's `ARCHITECTURE.md` "Clause auto-detection" + "Aliases" sections —
   the primitives the review engine will lean on.
