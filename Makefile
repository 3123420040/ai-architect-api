.PHONY: sprint1-demo sprint1-demo-local sprint1-ci sprint2-demo sprint2-demo-local sprint2-ci sprint3-demo sprint3-demo-local sprint3-ci sprint3-ci-linux sprint4-ci-linux test

PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python; fi)

sprint1-demo:
	PYTHONPATH=. $(PYTHON) -m app.services.professional_deliverables.demo --require-dwg

sprint1-demo-local:
	PYTHONPATH=. $(PYTHON) -m app.services.professional_deliverables.demo --allow-missing-dwg

sprint1-ci:
	PYTHONPATH=. $(PYTHON) -m app.services.professional_deliverables.demo --require-dwg
	PYTHONPATH=. $(PYTHON) -m pytest tests/professional_deliverables

sprint2-demo:
	PYTHONPATH=. $(PYTHON) -m app.services.professional_deliverables.sprint2_demo --require-external-tools

sprint2-demo-local:
	PYTHONPATH=. $(PYTHON) -m app.services.professional_deliverables.sprint2_demo --allow-missing-external-tools

sprint2-ci:
	PYTHONPATH=. $(PYTHON) -m app.services.professional_deliverables.sprint2_demo --require-external-tools
	PYTHONPATH=. $(PYTHON) -m pytest tests/professional_deliverables

sprint3-demo:
	PYTHONPATH=. $(PYTHON) -m app.services.professional_deliverables.sprint3_demo --require-external-tools

sprint3-demo-local:
	PYTHONPATH=. $(PYTHON) -m app.services.professional_deliverables.sprint3_demo --allow-missing-external-tools

sprint3-ci:
	PYTHONPATH=. $(PYTHON) -m app.services.professional_deliverables.sprint3_demo --require-external-tools
	PYTHONPATH=. $(PYTHON) -m pytest tests/professional_deliverables

test:
	PYTHONPATH=. $(PYTHON) -m pytest

sprint3-ci-linux:
	bash tools/sprint3/run-local-linux-parity.sh

sprint4-ci-linux:
	bash tools/sprint3/run-local-linux-parity.sh sprint4
