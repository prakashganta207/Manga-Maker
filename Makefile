# Thin wrapper around scripts/tasks.py (which also works on Windows without make).
PY ?= python3

.PHONY: install dev test backend frontend sample docker-up docker-down

install:
	$(PY) scripts/tasks.py install

dev:
	$(PY) scripts/tasks.py dev

test:
	$(PY) scripts/tasks.py test

backend:
	$(PY) scripts/tasks.py backend

frontend:
	$(PY) scripts/tasks.py frontend

sample:
	$(PY) scripts/tasks.py sample

docker-up:
	docker compose up --build

docker-down:
	docker compose down
