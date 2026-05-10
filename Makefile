.PHONY: help test test-quick build install clean smoke lint

help:
	@echo "Targets:"
	@echo "  test         Run the full test suite"
	@echo "  test-quick   Run a quick subset (no slow paths)"
	@echo "  build        Build wheel + sdist into dist/"
	@echo "  install      pipx install from current source"
	@echo "  smoke        Build, pipx install, run end-to-end smoke"
	@echo "  clean        Remove build artifacts"

test:
	python -m unittest discover -s tests -v

test-quick:
	python -m unittest discover -s tests -p 'test_meta_schema.py' -v

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
