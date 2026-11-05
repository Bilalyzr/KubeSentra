# KubeSentra Makefile.
# On Windows Git Bash `make` may be unavailable - use scripts/dev.sh instead
# (same targets). PY is the venv interpreter; Linux: .venv/bin/python.

PY ?= .venv/Scripts/python.exe

.PHONY: env up down ps migrate status test serve check lab-up lab-down lab-health fault-inject fault-clean

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

# --- Kubernetes laboratory (Phase 2) ---------------------------------------
# On Windows Git Bash (no make): run scripts/lab_up.sh etc. directly.

lab-up: ## Create/refresh the kind lab (cluster + boutique + monitoring + chaos)
	bash scripts/lab_up.sh

lab-down: ## Delete the kind lab cluster (Postgres is untouched)
	bash scripts/lab_down.sh

lab-health: ## Verify every lab layer (nodes, pods, targets, alerts, logs)
	bash scripts/lab_health.sh

fault-inject: ## Inject a fault scenario: make fault-inject S=oom_checkout
	bash scripts/inject_fault.sh $(S)

fault-clean: ## Clean up a fault scenario: make fault-clean S=oom_checkout
	bash scripts/cleanup_fault.sh $(S)

dashboard: ## Run the Streamlit dashboard (needs the API running)
	$(PY) -m streamlit run dashboard/app.py --server.port 8551 --server.headless true
