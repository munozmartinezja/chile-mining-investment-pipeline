.PHONY: setup data test lint

PYTHON ?= .venv/bin/python

setup:
	uv venv --python 3.12 .venv
	uv pip install --python $(PYTHON) -e .

data:
	$(PYTHON) -m cmip.load

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

