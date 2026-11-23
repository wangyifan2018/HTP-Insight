PY := .venv/bin/python
PORT ?= 8000

.PHONY: install doctor demo notebook test web mcp browser
install:
	bash scripts/install.sh

doctor:
	bash scripts/doctor.sh

demo:
	$(PY) -m examples.demo

notebook:
	$(PY) scripts/run_notebook.py

test:
	$(PY) -m pytest -q tests

web:
	npm --prefix web run build
	$(PY) -m uvicorn htp_insight.web:app --host 127.0.0.1 --port $(PORT)

mcp:
	@$(PY) -m htp_insight.mcp_server

browser:
	npm --prefix web run test:browser
