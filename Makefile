.PHONY: setup data survival portfolio analysis validation brief powerbi test lint

PYTHON ?= .venv/bin/python

setup:
	uv venv --python 3.12 .venv
	uv pip install --python $(PYTHON) -e .

data:
	$(PYTHON) -m cmip.load
	$(PYTHON) -m cmip.extract.sea
	$(PYTHON) -m cmip.match

survival:
	$(PYTHON) -m cmip.survival
	$(PYTHON) -m cmip.figures survival

portfolio:
	$(PYTHON) -m cmip.portfolio_status
	$(PYTHON) -m cmip.figures portfolio

analysis:
	$(MAKE) survival
	$(MAKE) portfolio

validation:
	$(PYTHON) -m cmip.validation

brief:
	$(PYTHON) -m cmip.brief

powerbi:
	$(PYTHON) -m cmip.powerbi

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .
