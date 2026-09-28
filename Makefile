PY ?= .venv/bin/python

.PHONY: setup data test lint todo

setup:
	python3 -m venv .venv
	$(PY) -m pip install -q -e ".[dev]"

data:
	$(PY) scripts/download_data.py

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check src tests scripts

# Lists every test still skipped because its function raises NotImplementedError.
todo:
	$(PY) -m pytest -q -rs | grep "not implemented yet" || echo "nothing left to implement"
