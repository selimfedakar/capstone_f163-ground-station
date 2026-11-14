.PHONY: install server sim test smoke

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

SERVER_HOST ?= 127.0.0.1
SERVER_PORT ?= 8000
SERVER_URL ?= ws://$(SERVER_HOST):$(SERVER_PORT)/ws/car

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

server:
	$(PY) -m uvicorn server.app.main:app --host $(SERVER_HOST) --port $(SERVER_PORT)

sim:
	$(PY) -m sim.car --server $(SERVER_URL) $(ARGS)

test:
	$(PY) -m pytest -q

smoke:
	bash scripts/smoke.sh
