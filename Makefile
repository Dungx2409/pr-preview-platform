SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

# Colors for terminal output
CYAN := \033[36m
GREEN := \033[32m
YELLOW := \033[33m
RED := \033[31m
RESET := \033[0m

.PHONY: help
help: ## Display available make targets
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  $(CYAN)%-18s$(RESET) %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: lint
lint: check-config lint-yaml lint-ansible lint-shell lint-python lint-secrets lint-helm lint-trivy ## Run all linters (yamllint, ansible-lint, shellcheck, ruff, gitleaks, helm, trivy)
	@echo -e "$(GREEN)✓ All linters passed!$(RESET)"

.PHONY: sync-config
sync-config: ## Synchronize platform manifests with root values.yaml
	@echo -e "$(CYAN)→ Synchronizing platform manifests with values.yaml...$(RESET)"
	@python3 scripts/sync-config.py

.PHONY: check-config
check-config: ## Verify platform manifests are in sync with values.yaml
	@echo -e "$(CYAN)→ Checking values.yaml synchronization...$(RESET)"
	@python3 scripts/sync-config.py --check

.PHONY: lint-yaml
lint-yaml: ## Lint YAML files
	@echo -e "$(CYAN)→ Running yamllint...$(RESET)"
	yamllint -c .yamllint.yaml .

.PHONY: lint-ansible
lint-ansible: ## Lint Ansible playbooks and roles
	@echo -e "$(CYAN)→ Running ansible-lint...$(RESET)"
	@if [ -f "ansible/requirements.yml" ]; then \
		ansible-galaxy collection install -r ansible/requirements.yml >/dev/null 2>&1 || true; \
	fi
	ansible-lint ansible/

.PHONY: lint-shell
lint-shell: ## Lint shell scripts with shellcheck
	@echo -e "$(CYAN)→ Running shellcheck...$(RESET)"
	@scripts=$$(find . -type f -name "*.sh" -not -path "./.venv/*" -not -path "./venv/*"); \
	if [ -n "$$scripts" ]; then \
		shellcheck $$scripts; \
	else \
		echo "No shell scripts found. Skipping shellcheck."; \
	fi

.PHONY: lint-python
lint-python: ## Lint and check formatting of Python code with ruff
	@echo -e "$(CYAN)→ Running ruff...$(RESET)"
	ruff check .
	ruff format --check .

.PHONY: lint-secrets
lint-secrets: ## Scan repository for secrets using gitleaks
	@echo -e "$(CYAN)→ Running gitleaks detect...$(RESET)"
	gitleaks detect --no-git --source . --verbose

.PHONY: lint-helm
lint-helm: ## Lint Helm charts
	@echo -e "$(CYAN)→ Running helm lint...$(RESET)"
	@if [ -f "charts/app/Chart.yaml" ]; then \
		helm lint charts/app; \
	fi

.PHONY: lint-trivy
lint-trivy: ## Scan filesystem and configurations for security issues with Trivy
	@echo -e "$(CYAN)→ Running trivy fs & config scan...$(RESET)"
	@if command -v trivy >/dev/null 2>&1; then \
		trivy fs --timeout 15m --severity CRITICAL,HIGH --ignore-unfixed --exit-code 1 .; \
		trivy config --timeout 15m --severity CRITICAL,HIGH --exit-code 1 .; \
	elif command -v docker >/dev/null 2>&1; then \
		mkdir -p "$${HOME}/.cache/trivy"; \
		docker run --rm -v "$${HOME}/.cache/trivy:/root/.cache" -v $$(pwd):/src -w /src aquasec/trivy:0.76.1 fs --timeout 15m --severity CRITICAL,HIGH --ignore-unfixed --exit-code 1 .; \
		docker run --rm -v "$${HOME}/.cache/trivy:/root/.cache" -v $$(pwd):/src -w /src aquasec/trivy:0.76.1 config --timeout 15m --severity CRITICAL,HIGH --exit-code 1 .; \
	else \
		echo "Trivy not installed and docker not available. Skipping."; \
	fi

.PHONY: test
test: ## Run unit tests (demo-app and exporter)
	@echo -e "$(CYAN)→ Running tests...$(RESET)"
	@if [ -d "demo-app/tests" ] || [ -d "exporter/tests" ] || [ -d "reaper/tests" ]; then \
		python3 -m pytest -v; \
	else \
		echo "No unit tests created yet (stub pass for T-0.4)."; \
	fi

.PHONY: tf-plan
tf-plan: ## Run terraform plan (read-only, Phase 8 cloud variant)
	@echo -e "$(YELLOW)Notice: Terraform is deferred to Phase 8 (cloud variant). Skipping.$(RESET)"

.PHONY: ansible-check
ansible-check: ## Run ansible-playbook in check/diff mode
	@echo -e "$(CYAN)→ Running ansible-playbook --check --diff...$(RESET)"
	@if [ -f "ansible/inventory/local.ini" ]; then \
		ansible-playbook -i ansible/inventory/local.ini ansible/site.yml --check --diff; \
	else \
		echo -e "$(RED)Error: ansible/inventory/local.ini not found. Copy local.ini.example first.$(RESET)"; \
		exit 1; \
	fi

.PHONY: helm-template
helm-template: ## Render Helm chart with sample values and validate
	@echo -e "$(CYAN)→ Rendering and validating Helm chart...$(RESET)"
	@if [ -f "charts/app/Chart.yaml" ]; then \
		helm lint charts/app; \
		if command -v kubeconform >/dev/null 2>&1; then \
			helm template test-app charts/app | kubeconform -summary -strict; \
		elif command -v docker >/dev/null 2>&1; then \
			helm template test-app charts/app | docker run --rm -i ghcr.io/yannh/kubeconform:v0.6.7 -summary -strict; \
		elif [ -f "$${HOME}/.kube/pr-preview.yaml" ]; then \
			helm template test-app charts/app | KUBECONFIG="$${HOME}/.kube/pr-preview.yaml" kubectl apply --dry-run=client -f -; \
		else \
			helm template test-app charts/app >/dev/null; \
		fi \
	else \
		echo "charts/app/Chart.yaml not found yet. Skipping until T-3.2."; \
	fi

.PHONY: verify-teardown
verify-teardown: ## Check no pr-* leftovers in the cluster
	@echo -e "$(CYAN)→ Verifying cluster teardown...$(RESET)"
	@if [ -f "scripts/verify-teardown.sh" ]; then \
		bash scripts/verify-teardown.sh; \
	else \
		echo "scripts/verify-teardown.sh not created yet. Skipping until T-4.6."; \
	fi

.PHONY: verify-security
verify-security: ## Run comprehensive security & isolation verification suite (T-5.2)
	@echo -e "$(CYAN)→ Running security verification...$(RESET)"
	@bash scripts/verify-security.sh
