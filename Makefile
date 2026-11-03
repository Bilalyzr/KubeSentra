# KubeSentra Makefile.
# On Windows Git Bash `make` may be unavailable - use scripts/dev.sh instead
# (same targets). PY is the venv interpreter; Linux: .venv/bin/python.

PY ?= .venv/Scripts/python.exe

.PHONY: env up down ps migrate status test serve check

env: ## Create the virtualenv and install pinned dependencies
	python -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

up: ## Start the Postgres container
	docker compose up -d postgres

down: ## Stop the compose stack (data volume is kept)
	docker compose down

ps: ## Show compose container status
	docker compose ps

migrate: ## Apply pending SQL migrations
	$(PY) -m database.migrate

status: ## Show applied/pending migrations
	$(PY) -m database.migrate --status

test: ## Run the test suite
	$(PY) -m pytest -v

serve: ## Run the API locally with auto-reload (port 8547; 8000 is taken by another app)
	$(PY) -m uvicorn api.main:app --host 127.0.0.1 --port 8547 --reload

check: ## Import-check every module, then run tests
	$(PY) -c "import common.config, database.connection, database.migrate, api.main; print('imports OK')"
	$(PY) -m pytest -v
