# Contributing

Thanks for the interest. Some ground rules so we keep the project small.

## Scope

`template-vault-cli` is a single-file Python CLI for storing, retrieving,
and structurally composing legal-document templates. It is deliberately not:

- a database;
- a SaaS;
- a generator of legal text (the LLM only picks which composition steps to
  run; clause text comes from existing templates).

Features that don't fit this scope are likely to be declined. If in doubt,
open an issue with a one-paragraph proposal first.

## Constraints

- **Stdlib only.** No third-party Python dependencies at runtime. If your
  change wants `requests` / `rich` / `pydantic` / etc., it doesn't fit.
- **Single-file CLI.** `template_vault_cli.py` stays one file. Tests live in
  `tests/`. Configs live in `config/`.
- **Privacy by default.** Any new command that could send template content
  off-machine must default to off, require explicit consent, and refuse in
  non-interactive contexts without that consent.

## Development

```bash
git clone git@github.com:DrBaher/template-vault-cli.git
cd template-vault-cli
python3 -m unittest discover -s tests -v
```

No virtualenv needed for tests — stdlib only.

To smoke-test the install path:

```bash
make smoke
```

## Tests

We aim for ≥ 60 tests covering schema, upload/retrieval, composition, LLM
flows, and `doctor`. Mock `urllib.request.urlopen` for any network paths;
your test should never make a real outbound call.

A new feature must include tests in the appropriate `tests/test_*.py` file.

## Commit messages

Subject + bullet body. Why-not-what.

```
swap: preserve target's H2 header on clause replacement

Otherwise the swapped-in numbering ("## 4. Term and Survival") gets
replaced by the source template's numbering, which silently breaks any
explicit clauses map that references the original anchor.
```

## Releases

`main` is always green (CI runs the full suite on Python 3.9–3.12 × Ubuntu /
macOS). Tag a release as `v0.X.Y`; `CHANGELOG.md` is the source of truth for
what's in it.
