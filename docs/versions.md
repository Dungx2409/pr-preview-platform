# Pinned Versions (`docs/versions.md`)

> **Rule:** Every component, image, chart, and GitHub action must have an explicit pinned version. Never use `latest`.
> All versions are verified against official release pages or the real local environment (SPEC v2.0 §4.2, AGENTS.md §4).

**Date checked:** 2026-10-23

---

## 1. Core Cluster & Platform Components

| Component | Pinned Version | Official Source URL | Notes |
|---|---|---|---|
| **k3s** | `v1.36.5+k3s1` | https://update.k3s.io/v1-release/channels/stable | Stable channel release. (Compatible with host kubectl `v1.35.9`) |
| **Argo CD** | `v3.5.6` (Chart `10.10.5`) | https://argoproj.github.io/argo-helm | GitOps engine for Tier 1 & Tier 2 previews. Pinned chart `argo/argo-cd:10.10.5` with AppVersion `v3.5.6` |
| **Tailscale Operator** | `1.104.2` | https://pkgs.tailscale.com/helmcharts | Helm chart `tailscale/tailscale-operator` |
| **kube-prometheus-stack** | `92.11.0` | https://prometheus-community.github.io/helm-charts | AppVersion: `v0.94.1`. Monitoring stack |

---

## 2. Infrastructure & Local Tools

| Tool / OS | Pinned Version | Official Source URL | Notes |
|---|---|---|---|
| **VirtualBox** | `7.2.10r174163` | `VBoxManage --version` | Local hypervisor on Linux host |
| **Host OS** | `Ubuntu 22.04.5 LTS` | `lsb_release -a` | Linux host (Intel 11th-gen, 24 GB RAM) |
| **Guest VM OS** | `Ubuntu Server 24.04 LTS` | https://releases.ubuntu.com/24.04/ | VM `devops-server` |
| **Ansible Core** | `2.16.19` | https://pypi.org/project/ansible-core/2.16.19/ | Local automation engine |
| **ansible-lint** | `26.10.1` | https://pypi.org/project/ansible-lint/26.10.1/ | Playbook linter |
| **kubectl** | `v1.35.9` | `kubectl version --client` | Local cluster CLI |
| **Helm** | `v3.22.1` | https://github.com/helm/helm/releases/tag/v3.22.1 | Package manager CLI |
| **Docker Engine** | `29.1.3` | `docker --version` | Local container runtime / builder |
| **Python** | `3.10.12` | https://www.python.org/downloads/release/python-31012/ | Host CLI & scripting runtime |
| **Yamllint** | `1.38.0` | https://pypi.org/project/yamllint/1.38.0/ | Manifest formatting linter |
| **ShellCheck** | `0.10.0` | https://github.com/koalaman/shellcheck/releases/tag/v0.10.0 | Shell script linter |
| **Ruff** | `0.11.11` | https://github.com/astral-sh/ruff/releases/tag/0.11.11 | Python linter and formatter |
| **Gitleaks** | `8.27.2` | https://github.com/gitleaks/gitleaks/releases/tag/v8.27.2 | Secret scanner |
| **kubeconform** | `v0.6.7` | https://github.com/yannh/kubeconform/releases/tag/v0.6.7 | Kubernetes manifest validator |

---

## 3. Container Images

| Image | Pinned Tag | Official Source URL | Notes |
|---|---|---|---|
| **Python Base Image** | `python:3.10-slim` | https://hub.docker.com/_/python | Demo app & preview-exporter base image |
| **FastAPI** | `0.161.1` | https://pypi.org/project/fastapi/ | Demo app web framework (Starlette 1.7.0, 0 CVEs) |
| **PostgreSQL** | `postgres:16-alpine` | https://hub.docker.com/_/postgres | Ephemeral database per preview namespace |
| **Trivy Scanner** | `v0.76.1` | https://github.com/aquasecurity/trivy/releases/tag/v0.76.1 | Image vulnerability scanner |

---

## 4. GitHub Actions

| Action | Pinned Tag / Ref | Official Source URL | Notes |
|---|---|---|---|
| `actions/checkout` | `v7.0.1` | https://github.com/actions/checkout/releases/tag/v7.0.1 | Repository checkout |
| `actions/setup-python` | `v7.1.0` | https://github.com/actions/setup-python/releases/tag/v7.1.0 | Python environment setup |
| `docker/login-action` | `v4.6.0` | https://github.com/docker/login-action/releases/tag/v4.6.0 | GHCR registry authentication |
| `docker/build-push-action` | `v7.4.0` | https://github.com/docker/build-push-action/releases/tag/v7.4.0 | Container image build and push |
| `aquasecurity/trivy-action` | `v0.36.0` | https://github.com/aquasecurity/trivy-action/releases/tag/v0.36.0 | Automated CI vulnerability scanning |
