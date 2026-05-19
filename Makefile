.PHONY: help test test-quick build install clean smoke lint coverage typecheck release spec-check

help:
	@echo "Targets:"
	@echo "  test                    Run the full test suite"
	@echo "  test-quick              Run a quick subset (no slow paths)"
	@echo "  coverage                Run tests under coverage.py and print a report"
	@echo "  typecheck               Run mypy --strict on template_vault_cli.py"
	@echo "  spec-check              Lint docs/spec/*.schema.json files for JSON validity"
	@echo "  build                   Build wheel + sdist into dist/"
	@echo "  install                 pipx install from current source"
	@echo "  smoke                   Build, pipx install, run end-to-end smoke"
	@echo "  release VERSION=X.Y.Z   Bump + promote CHANGELOG + commit + tag"
	@echo "  clean                   Remove build artifacts"

test:
	python -m unittest discover -s tests -v

test-quick:
	python -m unittest discover -s tests -p 'test_meta_schema.py' -v

coverage:
	python -m pip install --quiet --upgrade 'coverage>=7.0'
	python -m coverage erase
	python -m coverage run -m unittest discover -s tests -v
	python -m coverage report

typecheck:
	python -m pip install --quiet --upgrade 'mypy>=1.10'
	python -m mypy --strict template_vault_cli.py

release:
	@if [ -z "$(VERSION)" ]; then \
		echo "Usage: make release VERSION=X.Y.Z"; exit 2; \
	fi
	python scripts/release.py $(VERSION)

spec-check:
	@echo "Validating docs/spec/*.schema.json are well-formed JSON..."
	@for f in docs/spec/*.schema.json; do \
		python -c "import json,sys; json.load(open('$$f')); print('  ok: $$f')" \
			|| (echo "  FAIL: $$f"; exit 1); \
	done

build:
	python -m pip install --quiet --upgrade build hatchling
	python -m build

install:
	pipx install --force .

smoke: build
	pipx install --force dist/*.whl
	template-vault --version
	rm -rf /tmp/tv-smoke && mkdir -p /tmp/tv-smoke && \
	  cd /tmp/tv-smoke && \
	  template-vault init && \
	  template-vault sources && \
	  echo "smoke ok"

clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
