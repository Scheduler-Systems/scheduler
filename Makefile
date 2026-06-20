# Scheduler open core — top-level dev orchestration.
.PHONY: help dev dev-docker seed

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

dev: ## Run the whole stack locally with zero external accounts (emulators + API + web)
	@./scripts/dev.sh

dev-docker: ## Same, but in containers (only Docker required) — see docker-compose.yml
	@docker compose up --build

seed: ## Seed the test user into a running Auth emulator
	@./scripts/seed-dev.sh
