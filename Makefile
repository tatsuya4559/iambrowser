.DEFAULT_GOAL := help

pipcompile: ## Generate requirements.txt
	pip-compile
	pip-compile dev-requirements.in

.PHONY: pipsync
pipsync: pipcompile ## Install python libraries
	pip-sync requirements.txt dev-requirements.txt

.PHONY: run
run: ## Run application
	@python main.py

.PHONY: dev
dev: ## Run in debug mode
	textual run --dev main.py

.PHONY: console
console: ## Run debug console
	textual console -v

.PHONY: help
help: ## Display this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

