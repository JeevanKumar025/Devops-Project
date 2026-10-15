.PHONY: test up down local smoke k8s-local

test:            ## run all unit tests (no Docker needed)
	python3 -m unittest discover -s . -t . -v

up:              ## start everything with Docker Compose
	docker compose up --build -d

down:
	docker compose down -v

local:           ## run everything WITHOUT Docker (SQLite)
	python3 scripts/run_local.py

smoke:           ## end-to-end checks against a running system
	python3 scripts/smoke_test.py http://localhost:8080
	python3 scripts/ui_smoke_test.py http://localhost:8080
