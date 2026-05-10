## What

<!-- One-paragraph description of the change. -->

## Why

<!-- Why this change, not what it does line-by-line. -->

## Tests

- [ ] `python -m unittest discover -s tests -v` passes locally
- [ ] New tests added for the change (or N/A: doc/CI/registry only)
- [ ] No new third-party Python dependencies introduced

## Privacy / scope check

- [ ] If this changes what `ask` sends to the LLM, the new behavior defaults
      to off and requires explicit consent in non-interactive contexts.
- [ ] This change keeps `template-vault-cli` to its scope: structures
      existing templates; does not generate clause text.
