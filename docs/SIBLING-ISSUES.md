# Drafts: issues to open against sibling repos

These are paste-ready issue bodies for the five sibling CLIs. They flow
from the v0.4.7 / v0.4.8 audit. Open them at your convenience; nothing
here is urgent and template-vault-cli works fine without these landing.

Group A (small docs fix): one issue per pipeline CLI to update the suite
framing. Group B (substantive): one issue against compare-cli to fix
the "forthcoming" line. Group C (optional ergonomics): one issue against
nda-review-cli to adopt the shared `~/.config/contract-ops/` config dir.

---

## 1. Against `DrBaher/draft-cli` — README suite framing

**Title:** docs: add template-vault-cli to the suite-chain framing

**Body:**

The README's "Part of the contract-ops CLI suite" header lists
draft → review → convert → sign but doesn't reference
[template-vault-cli](https://github.com/DrBaher/template-vault-cli)
(the storage layer that feeds `draft-cli` via `template-vault get <ref>`)
or [compare-cli](https://github.com/DrBaher/compare-cli) (the auxiliary
drift detector).

template-vault-cli landed in v0.4.x with full `info --json` output that
draft-cli could consume to know what placeholders to expect. Suggested
reframe (matches the convention now in template-vault-cli v0.4.7 and
compare-cli's spec):

```
> Part of the contract-ops CLI suite. **draft-cli** (fill placeholders) →
> [**nda-review-cli**](...) (review, redline, negotiate) →
> [**docx2pdf-cli**](...) (DOCX → PDF) →
> [**sign-cli**](...) (signing + audit).
> Storage layer: [**template-vault-cli**](https://github.com/DrBaher/template-vault-cli).
> Drift detection: [**compare-cli**](https://github.com/DrBaher/compare-cli).
> [Showcase site](https://cli.drbaher.com/).
```

template-vault-cli also publishes JSON Schemas at
[docs/spec/](https://github.com/DrBaher/template-vault-cli/tree/main/docs/spec)
including `info-json.schema.json`. If draft-cli grows a
`--from-vault <ref>` flag, it can pull placeholder metadata against
that schema instead of inventing a parallel contract.

---

## 2. Against `DrBaher/nda-review-cli` — same README fix, plus shared LLM config

**Title:** docs+ux: surface template-vault-cli in suite framing; adopt shared LLM config dir

**Body:**

Two pieces:

### A. README suite framing

template-vault-cli (v0.4.x) is the storage layer that nda-review-cli
already integrates with via `info --json` and `get`. Suggest updating
the suite header to reference it explicitly:

```
> Part of the contract-ops CLI suite.
> [**draft-cli**](...) (fill placeholders) →
> **nda-review-cli** (review, redline, negotiate) →
> [**docx2pdf-cli**](...) (DOCX → PDF) →
> [**sign-cli**](...) (signing + audit).
> Storage layer: [**template-vault-cli**](https://github.com/DrBaher/template-vault-cli).
> Drift detection: [**compare-cli**](https://github.com/DrBaher/compare-cli).
```

### B. Adopt `~/.config/contract-ops/llm.json` as the preferred config location

template-vault-cli v0.4.8 added a suite-wide LLM config lookup:

```
~/.config/contract-ops/llm.json        # NEW: preferred
~/.config/nda-review-cli/llm.json      # legacy
~/.config/template-vault-cli/llm.json  # legacy
```

If nda-review-cli adopts the same lookup order, users get a single
config file driving every Python suite tool. Backward-compatible — the
existing per-CLI paths continue to work.

Spec for the file shape lives in
[template-vault-cli/docs/INTEROP.md](https://github.com/DrBaher/template-vault-cli/blob/main/docs/INTEROP.md#shared-llm-config).

---

## 3. Against `DrBaher/compare-cli` — fix "forthcoming" + add to chain

**Title:** docs: template-vault-cli has shipped; remove "forthcoming"

**Body:**

The README's suite-tools list currently has:

> ... `template-vault-cli` (forthcoming)

`template-vault-cli` has been at v0.4.x for a while; the "forthcoming"
note is stale. Should be a regular link:

> [`template-vault-cli`](https://github.com/DrBaher/template-vault-cli) — clause-aware template storage; produces `info --json` payloads that downstream tools consume.

While we're updating, compare-cli is positioned in the template-vault
README as the "auxiliary drift detector" sitting next to the pipeline
(rather than as a chain step). If you prefer that framing for symmetry,
both READMEs would line up.

Also, the
[docs/clause-detection.md](https://github.com/DrBaher/compare-cli/blob/main/docs/clause-detection.md)
spec template-vault-cli implements is documented in
[template-vault-cli/docs/clause-detection-divergence.md](https://github.com/DrBaher/template-vault-cli/blob/main/docs/clause-detection-divergence.md)
with the 10 known divergences. Reconciliation isn't urgent on either
side but the diff is now precise.

---

## 4. Against `DrBaher/docx2pdf-cli` — README suite framing

**Title:** docs: add template-vault-cli to the suite-chain framing

**Body:**

Same as the draft-cli issue: the suite-header chain
(draft → review → docx2pdf → sign) is missing the storage layer and the
drift detector. Suggested update — adopt the same line shape the other
CLIs are converging on:

```
> Part of the contract-ops CLI suite. [draft-cli] → [nda-review-cli] →
> **docx2pdf-cli** → [sign-cli]. Storage: [template-vault-cli]. Drift: [compare-cli].
```

---

## 5. Against `DrBaher/sign-cli` — README suite framing

**Title:** docs: add template-vault-cli to the suite-chain framing

**Body:**

Same as the draft-cli / docx2pdf-cli issues — the linear suite chain
in the README header should also mention the storage and drift-detection
auxiliaries:

```
> Part of the contract-ops CLI suite. [draft-cli] → [nda-review-cli] →
> [docx2pdf-cli] → **sign-cli**. Storage: [template-vault-cli]. Drift: [compare-cli].
```

---

## 6. Optional: a `drbaher/contract-ops-specs` repo

Not really an issue but a strategic note. As the suite grows, having
specs (clause-detection rule, policy schema, INTEROP doc) live in
consumer repos creates awkward ownership questions. When you have ~3-4
specs that span multiple CLIs, hoisting them to a neutral
`drbaher/contract-ops-specs` repo would be cleaner.

For now, every spec lives in its producing repo and gets cited by
consumers. That's fine while there are only two cross-repo specs
(clause-detection in compare-cli; INTEROP in template-vault-cli).
