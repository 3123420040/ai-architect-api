.PHONY: sprint1-demo sprint1-demo-local sprint1-ci test

PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python; fi)

sprint1-demo:
	PYTHONPATH=. $(PYTHON) -m app.services.professional_deliverables.demo --require-dwg

sprint1-demo-local:
	PYTHONPATH=. $(PYTHON) -m app.services.professional_deliverables.demo --allow-missing-dwg

sprint1-ci:
	PYTHONPATH=. $(PYTHON) -m app.services.professional_deliverables.demo --require-dwg
	PYTHONPATH=. $(PYTHON) -m pytest tests/professional_deliverables

test:
	PYTHONPATH=. $(PYTHON) -m pytest
