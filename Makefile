.DEFAULT_GOAL := help

################################################################################
# Dependencies
################################################################################

requirements.txt: requirements.in
	pip-compile

dev-requirements.txt: dev-requirements.in
	pip-compile dev-requirements.in

.PHONY: pipsync
pipsync: requirements.txt dev-requirements.txt
	pip-sync requirements.txt dev-requirements.txt

.git/hooks/pre-commit: .pre-commit-config.yaml
	pre-commit install

################################################################################
# Commands
################################################################################

.PHONY: prepare
prepare: pipsync .git/hooks/pre-commit ## Prepare for development

.PHONY: run
run: ## Run application
	python iambrowser/main.py

.PHONY: dev
dev: ## Run in debug mode
	textual run --dev iambrowser/main.py

.PHONY: console
console: ## Run debug console
	textual console -v

.PHONY: help
help: ## Display this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

