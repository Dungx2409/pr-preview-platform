# AGENTS.md — Operating rules for AI agents

You are helping **Dũng** (the owner) build the **PR Preview Platform**, a personal portfolio project for DevOps/Cloud intern applications. Read this file fully before doing anything. Keep it short in your head: the rules below are the ones that matter.

## 1. Read order (every session)

1. `AGENTS.md` (this file)
2. `TASK.md` → find **Current focus** and the next unchecked task whose dependencies are done
3. `SPEC.md` → only the sections relevant to that task (the source of truth for *what* and *why*)
4. `DEVLOG.md` → the last 2–3 session entries + **Decisions** + **Gotchas**

Never start coding before you can state, in one sentence, which task ID you are doing and what "done" means for it.

## 2. Project in 5 lines

- Every labeled PR gets `https://pr-<N>.preview.<DOMAIN>`; closing the PR removes everything.
- Stack: GCP VM + single-node **k3s**, **Terraform** (cloud) + **Ansible** (node), **Argo CD ApplicationSet** (GitOps), **GitHub Actions** + GHCR, **cert-manager** wildcard TLS, **Prometheus/Grafana**, **Trivy**.
- CI builds; the cluster **pulls** from Git. CI never holds cluster credentials.
- Goal is a **demoable, measured, understandable** project, not a feature-rich one.
- Full details: `SPEC.md`.

## 3. Working loop (one task at a time)

1. **Plan** (≤10 lines): files you will touch, approach, how you will verify. For anything non-trivial, show the plan and wait for the owner's OK.
2. **Branch**: `task/T-<id>-<short-name>` (e.g. `task/T-1.2-terraform-network`). Never commit to `main`.
3. **Implement in small steps.** One task = one small PR-sized change. No unrelated refactors, no drive-by features.
4. **Verify** with the commands in §7. Paste the real output summary (not "should work").
5. **Update docs**: tick the task in `TASK.md`, add a session entry in `DEVLOG.md` (§8), update `SPEC.md` only if behavior/design changed (and say so).
6. **Commit** with Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `ci:`, `infra:`), referencing the task ID: `infra: add static IP and firewall (T-1.2)`.
7. **Stop and report** (see §9). Do not chain into the next task unless asked.

## 4. Permission levels

**✅ Do freely** — read/edit files in the repo, run linters/tests/`terraform fmt|validate|plan`, `helm lint|template`, `ansible-lint`, `ansible-playbook --check`, local `docker build`, read-only `kubectl get|describe|logs`.

**🟡 Ask first (show the exact command + expected effect, wait for "ok")**
- `terraform apply|destroy|import|state *`, anything that creates/changes/deletes **cloud resources or costs money**
- `ansible-playbook` against the real host (without `--check`)
- `kubectl apply|delete|patch|edit|drain` or `helm install|upgrade|uninstall` on the real cluster
- Installing system packages or tools on the owner's machine
- Adding a new dependency, a new tool, or a new third-party GitHub Action
- Changing anything in `SPEC.md` §4 (Decisions) or §9 (Security)

**⛔ Never**
- Commit secrets, tokens, kubeconfigs, `.tfstate`, `.tfvars` with real values, private keys, or `.env` files. If you see one staged, stop and tell the owner.
- Print secrets in logs/outputs, or paste them into chat.
- `git push --force`, rewrite shared history, push to `main`, disable branch protection.
- Weaken security controls to "make it work" (open 6443, disable NetworkPolicy/PSS, `privileged: true`, `latest` tags, `pull_request_target` running PR code, `--insecure`/`-k` flags).
- Touch namespaces/resources that are not part of this project (`kube-system` excluded from edits; only create/modify what the SPEC names).
- Invent versions, flags, API fields, or resource names from memory. **Verify against official docs for the pinned version** and cite the doc in the DEVLOG.

## 5. Human-in-the-loop tasks (👤)

Some steps need the owner (billing account, domain/DNS tokens, GitHub settings, SSH keys, running `apply`). When you reach one: stop, write exactly **what to do, where to click/run, and what to send back** (never ask for secret values in chat — tell them to put them in env/secret stores). Mark the task `[!]` blocked until confirmed.

## 6. When unsure or when things disagree

- If SPEC and reality disagree, or two requirements conflict: **stop, explain in 3–5 lines, propose 2 options with a recommendation, wait.** Do not silently pick.
- If a task is bigger than ~half a day of work, split it in `TASK.md` first.
- If you are stuck after 2 serious attempts, write what you tried + hypotheses in `DEVLOG.md` → Gotchas and ask.
- Do not widen scope. New ideas go to `DEVLOG.md` → **Ideas parking lot**.

## 7. Verification commands (keep this section current)

Target `make` interface (create in T-0.4; extend as the repo grows):

| Command | Purpose |
|---|---|
| `make lint` | all linters (terraform fmt/validate/tflint, ansible-lint, helm lint, ruff, hadolint, yamllint, gitleaks) |
| `make test` | demo-app + exporter unit tests |
| `make tf-plan` | `terraform plan` (read-only) |
| `make ansible-check` | `ansible-playbook --check --diff` |
| `make helm-template` | render chart with sample values and validate (kubeconform) |
| `make verify-teardown` | check no `pr-*` leftovers (needs cluster access; read-only) |

A task is **not done** until its acceptance criteria in `TASK.md` pass and `make lint && make test` are green (where applicable).

## 8. DEVLOG protocol (important — this is how future sessions get context)

After each task, append a session entry to `DEVLOG.md` using the template there. Always include:
- **What** changed (files, task ID) and **Why** this approach
- **Verified** (commands + result)
- **Gotchas/decisions** discovered (also add to the Decisions or Gotchas sections if lasting)
- **Learned / interview note**: 2–4 lines in plain English explaining the concept the owner should be able to explain

Measured numbers (time-to-ready, rebuild time…) go in the **Metrics** table, with date and method. Never write a number you did not measure.

## 9. Reporting back (end of every task)

Reply to the owner in **Vietnamese, casual (mày/tao is fine)**, short and scannable:
1. ✅ Done: task ID + 1–2 lines
2. 🔍 Evidence: what you ran and the result
3. 📚 Concept to understand: 1–2 lines (why this works)
4. ⚠️ Risks / things you are unsure about
5. ➡️ Proposed next task (wait for confirmation)

Code, comments, commit messages, and repo docs are in **English**.

## 10. Learning mode (owner wants to understand, not just receive code)

- Prefer the **simplest** solution that satisfies the SPEC. No clever abstractions, no extra frameworks.
- Explain non-obvious choices in comments or DEVLOG (*why*, not *what*).
- Keep diffs reviewable (target < ~300 changed lines per task). No giant generated dumps.
- For each new tool/concept (e.g. DNS-01, ApplicationSet, NetworkPolicy), give a 3–5 line plain explanation and one "how to check it works" command.
- If the owner asks "why?", answer the question before continuing the task.

## 11. Code & config conventions

- **General:** pin every version (images, charts, providers, actions, tools). No `latest`. Prefer explicit over implicit. Fail fast, readable errors.
- **Terraform:** `fmt`ed, variables typed + described, no hardcoded project IDs/IPs/secrets, sensitive outputs marked, remote state in GCS, small files by concern, `terraform plan` shown before any apply.
- **Ansible:** roles, idempotent (second run = 0 changed), `become` only where needed, no shell when a module exists, tags where useful.
- **Kubernetes/Helm:** requests+limits on every container, probes, non-root, `readOnlyRootFilesystem` where possible, labels (`app.kubernetes.io/*`, `preview=true`, `pr=<N>`), no hostPath, no privileged.
- **GitHub Actions:** minimal `permissions:` per job, pin actions, no secrets to untrusted code, concurrency groups per PR, timeouts on jobs.
- **Python (demo-app, exporter):** type hints, `ruff` clean, tests with pytest, config via env vars, structured logging, no secrets in logs.
- **Shell:** `set -euo pipefail`, shellcheck clean, idempotent, print what it does.
- **Docs:** concise; diagrams as Mermaid or ASCII; every doc says how to verify the thing it describes.

## 12. Definition of done (per task)

- [ ] Acceptance criteria in `TASK.md` met, with evidence
- [ ] `make lint` / `make test` green (if applicable)
- [ ] No secrets or state files in the diff
- [ ] `TASK.md` ticked, `DEVLOG.md` entry added
- [ ] Owner can explain what changed and why (§10)

## 13. Known traps (read once)

- Let's Encrypt **rate limits** → use **staging** issuer first; one wildcard cert, never one per PR.
- The ApplicationSet can sync **before** CI pushes the image → transient `ImagePullBackOff` is expected.
- Argo CD may **not** delete the namespace when the Application is deleted → verify and handle (SPEC §6.4).
- k3s default CIDRs and the Traefik TLSStore API group depend on versions → **check, don't assume**.
- GCP: pods can reach the **metadata server** (`169.254.169.254`) unless blocked → NetworkPolicy must deny it.
- A stopped VM still bills for disk and static IP; a running VM burns credits → ask before leaving anything running.
- GHCR packages are private by default; the first push needs the package set to public (👤 step).
