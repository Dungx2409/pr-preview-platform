# TASK.md — Backlog (aligned with SPEC v2.0)

> Legend: `[ ]` todo · `[~]` in progress / done but acceptance not yet verified · `[x]` done · `[!]` blocked
> Owner: 🤖 agent · 👤 owner (human only) · 🤝 pair (agent prepares, owner runs/approves)
> Rules: one task at a time, in ID order unless dependencies allow otherwise. After each task update this file and `DEVLOG.md`. *What/why* lives in `SPEC.md`; *how to work* lives in `AGENTS.md`.
> Direction (SPEC v2.0): **local VirtualBox VM + k3s, private sharing through a Tailscale tailnet**. Two tiers: **Tier 1** shared environment, **Tier 2** per-PR previews. No GCP, no domain needed until Phase 8 (optional).
> IDs T-1.1 – T-1.4 are intentionally unused (Terraform/cloud content moved to T-8.1).

## Current focus

**→ Phase 5 — Hardening + cleanup (T-5.1 Reaper CronJob)**

---

## Phase 0 — Foundation

- [x] **T-0.1** 👤 **Prerequisites checklist**
  - GitHub: **public** repo `pr-preview-platform`; Actions enabled; branch protection on `main` (PR required, status checks); label `preview` created.
  - Local tools installed: git, VirtualBox, ansible, ansible-lint, kubectl, helm, docker, make, python 3, yamllint, shellcheck, gitleaks.
  - Tailscale: free account + tailnet created; MagicDNS + HTTPS enabled; **neutral device names** (no personal info — HTTPS publishes names in public certificate logs).
  - Confirm the Ubuntu Server VM exists (NAT + host-only adapters) and note its real RAM/vCPU/disk.
  - Send back (no secret values!): GitHub owner/repo, VM specs, tailnet name.
  - *Acceptance:* owner confirms each bullet. Repo `Dungx2409/pr-preview-platform` created, Actions green, branch protection active.

- [x] **T-0.2** 🤖 **Repo skeleton**
  - Create the layout from SPEC §5 (keep `infra/terraform/` as an empty placeholder with a README saying "Phase 8"), `.gitignore` (kubeconfig, `*.pem`, `.env`, `.venv`, `inventory/local.ini`, tfstate/tfvars…), `.editorconfig`, README stub, PR template referencing task IDs, `CODEOWNERS`.
  - *Acceptance:* tree matches SPEC §5; secret-like files are ignored; README states the project goal in 3 lines.

- [x] **T-0.3** 🤖 **Pin versions** (depends T-0.2)
  - Look up current stable releases **from official sources** and fill `docs/versions.md` (version + source URL + date checked) for everything in SPEC §4.2.
  - *Acceptance:* every listed tool/chart/image has a pinned version and a link; nothing taken from memory.

- [x] **T-0.4** 🤖 **Makefile + pre-commit + base CI** (depends T-0.3)
  - `make lint` and `make test` wired to real tools (yamllint, ansible-lint, shellcheck, gitleaks, helm lint when charts exist); pre-commit hooks; `.github/workflows/ci.yml` running `make lint`.
  - *Acceptance:* CI green on a trivial PR; a fake secret on a throw-away branch is caught by gitleaks (then removed).

## Phase 1 — Local VM + Ansible

- [x] **T-1.0** 🤝 **Local VM documented and snapshotted**
  - Record real VM spec, adapters (NAT + host-only) and addressing in `docs/runbook.md` (no secrets); SSH key-only login from the host works; take a **base snapshot** before Ansible changes; write "recreate the VM from scratch" steps.
  - *Acceptance:* a second person could recreate the VM from the runbook; snapshot name recorded in DEVLOG.

- [x] **T-1.5** 🤖 **Ansible role `common`** (depends T-1.0)
  - apt upgrade, unattended-upgrades, SSH hardening (key-only, no root login), fail2ban, timezone, swap decision (logged). Static inventory for the local VM (`inventory/local.ini` git-ignored + `.example`).
  - *Acceptance:* `--check` clean; real run OK (🟡); **second run = 0 changed**; `ansible-lint` clean.

- [x] **T-1.6** 🤖 **Ansible role `k3s`** (depends T-1.5)
  - Pinned k3s, documented flags and why, kubeconfig stored **outside the repo**, wait for node Ready.
  - *Acceptance:* `kubectl get nodes` Ready from the host via the host-only interface; **6443 not reachable from the LAN/internet** (verify from a second device or by firewall rules); idempotent rerun; VM RAM headroom recorded in DEVLOG Metrics.

## Phase 2 — Cluster platform (private access)

- [x] **T-2.0** 🤝 **Tailscale private-Ingress spike (go/no-go)** (depends T-1.6)
  - Owner prepares (agent drafts JSON/instructions only): tailnet policy with `tagOwners`, `group:reviewers`, access rule to proxies on 443; OAuth client for the operator (scopes per **current** docs); credentials passed out-of-band.
  - Agent installs the Tailscale Operator (pinned) in namespace `spike-ts`, deploys a test app with an Ingress (`ingressClassName: tailscale`, **no funnel**).
  - Measure and record (real numbers): time from Ingress creation → reachable by a **second tailnet member**; first-connection TLS delay; RAM/CPU of operator + each proxy pod with 1, 3, 5 Ingresses; behavior when deleting an Ingress (proxy pod and tailnet device gone?) and when recreating the same hostname (renamed?); changing the hostname of an existing Ingress; **tagged-resource count and ephemeral-minutes usage after several hours**.
  - Verify: a **non-member** cannot reach the URL; a member outside `group:reviewers` cannot either.
  - Research the "is the preview up?" options A/B/C (SPEC §6.7) and recommend one.
  - *Acceptance:* ≤ 1-page comparison in `docs/decisions.md` (Tailscale operator vs fallback D13) with **measured numbers**, risks, and a clear GO/NO-GO; DEVLOG updated; spike namespace cleaned. **After the owner decides:** GO → proceed with T-2.1/T-2.2 as written; NO-GO → owner picks the D13 fallback and the agent rewrites T-2.1/T-2.2/T-3.4/T-4.4 accordingly.

- [x] **T-2.1** 🤝 **Tailscale Operator install (managed by the repo)** (depends T-2.0 = GO)
  - Values + install script under `platform/bootstrap/` and `platform/tailscale/`; policy snippet committed as a *draft* file (owner pastes it); no credentials in Git.
  - *Acceptance:* operator Ready; a test Ingress gets a valid `https://<name>.<tailnet>.ts.net` for a tailnet member.

- [x] **T-2.2** 🤖 **Access-model verification** (depends T-2.1)
  - Script/runbook that proves: member in `group:reviewers` → access; member outside the group → denied; non-member → denied; nothing exposed publicly.
  - *Acceptance:* results table in `docs/security.md`.

- [x] **T-2.3** 🤝 **Argo CD install + access** (depends T-1.6)
  - Pinned install; UI **not exposed** (port-forward from the host or owner-only tailnet); initial admin secret rotated; GitHub read-only token Secret created out-of-band.
  - *Acceptance:* login works via port-forward; Argo CD UI not reachable by other tailnet members or the LAN.

- [x] **T-2.4** 🤖 **AppProject `previews`** (depends T-2.3)
  - Allowed source repo(s) explicit; destinations = `shared` and `pr-*` only; cluster-resource whitelist = `Namespace`.
  - *Acceptance:* an Application targeting any other namespace is rejected (documented test).

## Phase 3 — Demo app, chart, Tier 1 shared environment

- [x] **T-3.1** 🤖 **Demo app** — FastAPI per SPEC §6.6, pytest, multi-stage non-root Dockerfile.
  - *Acceptance:* `make test` green; local `docker build` + run returns the expected JSON; runs as non-root.

- [x] **T-3.2** 🤖 **Helm chart `charts/app`** (depends T-3.1)
  - Deployment, Service, Ingress (class + hostname from values), ephemeral Postgres, ServiceAccount, probes, securityContext, resources.
  - *Acceptance:* `helm lint` + `helm template | kubeconform` clean; sensible `values.yaml`; Ingress hostname is set at creation (not patched later).

- [x] **T-3.3** 🤖 **Isolation objects** (depends T-3.2) — ResourceQuota, LimitRange, default-deny NetworkPolicy + allows, PSS labels.
  - *Acceptance:* rendered manifests reviewed; a quota-exceeding test is rejected.

- [x] **T-3.4** 🤝 **Manual deploy to `pr-0`** (depends T-3.3, T-2.1)
  - Push image to GHCR (package public, 👤); `helm install` into `pr-0` (🟡).
  - *Acceptance:* a tailnet member opens `https://pr-0.<tailnet>.ts.net`; DB counter works; from the pod, other namespaces and any metadata address are unreachable; then uninstall and delete `pr-0` with no leftovers (incl. proxy/device).

- [x] **T-3.5** 🤝 **Tier 1 — shared environment** (depends T-3.4, T-2.4)
  - `build.yml` on push to `main`: build → Trivy → push GHCR tag = commit SHA. Argo CD `Application shared-main` (namespace `shared`) tracks `main` and the image tag in `values.yml`.
  - *Acceptance:* change the tag in `values.yml` → Argo CD syncs → `https://shared.<tailnet>.ts.net` shows the new `sha`; a teammate (second member) confirms; time from merge to visible recorded.

## Phase 4 — CI + per-PR previews (Tier 2)

- [x] **T-4.1** 🤖 **`ci.yml` full** — app tests, `helm lint`/kubeconform, ansible-lint, yamllint, shellcheck, Trivy config+fs, gitleaks.
  - *Acceptance:* required status checks configured; a deliberately broken change fails CI.

- [x] **T-4.2** 🤖 **`preview.yml` build + scan + push** (depends T-3.1)
  - Gates: label `preview` AND same-repo PR; Trivy image scan (HIGH/CRITICAL fail); push `pr-<N>-<shortsha>`; concurrency per PR; least-privilege permissions; timeouts.
  - *Acceptance:* a labeled PR pushes the expected tag; an unlabeled PR and a simulated fork PR do **not** run the job.

- [x] **T-4.3** 🤖 **ApplicationSet** (depends T-2.4, T-3.4)
  - Per SPEC §6.4 (verify fields against pinned docs); repo/owner/chart path parameterized; `requeueAfterSeconds` tuned. **Record in DEVLOG:** is the namespace deleted with the Application? Is the proxy pod/tailnet device removed? Fix if not.
  - *Acceptance:* labeled PR ⇒ Application `preview-pr-<N>` Healthy/Synced; removing the label ⇒ Application, namespace and tailnet device gone.

- [x] **T-4.4** 🤖 **PR comment + Deployment status** (depends T-4.2, T-4.3)
  - Implement the mechanism chosen in T-2.0 (A/B/C, SPEC §6.7): ONE upserted PR comment with the private link; Deployment status for environment `pr-<N>`.
  - *Acceptance:* comment appears once and updates on new pushes; a tailnet member opens the link from the comment; time-to-ready recorded in DEVLOG Metrics.

- [x] **T-4.5** 🤖 **`preview-closed.yml` cleanup** — delete GHCR tags for the PR, deactivate Deployment, final comment.
  - *Acceptance:* closing/merging a PR leaves no tags, namespace, Application, proxy pod or tailnet device.

- [x] **T-4.6** 🤖 **`scripts/verify-teardown.sh` + 20-cycle test**
  - Script lists leftovers (namespaces, PVs, Applications, GHCR tags, Tailscale devices). Run 20 open/close cycles (script-assisted).
  - *Acceptance:* **0 leaks**; teardown time recorded.

- [ ] **T-4.7** 🤝 *(optional)* **Push-based comparison spike** — short experiment to write up pull vs push trade-offs in `docs/decisions.md`; not merged into the main flow.

## Phase 5 — Hardening + cleanup

- [ ] **T-5.1** 🤖 **Reaper CronJob** (dry-run first) per SPEC §6.9.
  - *Acceptance:* an orphan namespace older than TTL is detected (dry-run), then reaped after the owner enables delete mode; stale Tailscale devices checked.

- [ ] **T-5.2** 🤖 **Security verification** — fork-safety, no CI cluster credentials, 6443/Argo CD UI not exposed, NetworkPolicy, PSS, non-root, ACL group behavior.
  - *Acceptance:* `docs/security.md` has a table: control → how verified → result.

- [ ] **T-5.3** 🤝 **Secrets & access hygiene review** — history scan with gitleaks; token scopes and Tailscale OAuth scopes re-checked; rotation steps in the runbook and tried once; list of tailnet members/groups reviewed.
  - *Acceptance:* clean scan; rotation documented and tested once.

## Phase 6 — Observability + metrics

- [ ] **T-6.1** 🤝 **Monitoring stack** (depends T-2.3) — pinned install, reduced retention/limits, reachable via port-forward or owner-only access.
  - *Acceptance:* Grafana opens; VM memory headroom and max concurrent previews recorded in DEVLOG.

- [ ] **T-6.2** 🤖 **preview-exporter** (Python) — metrics per SPEC §6.8, unit tests, Deployment manifest, ServiceMonitor.
  - *Acceptance:* metrics visible in Prometheus for a live preview.

- [ ] **T-6.3** 🤖 **Dashboard + alerts** — committed JSON; VM memory alert; operator/proxy RAM panel.
  - *Acceptance:* dashboard shows real data; alert rule validated (promtool or a test fire).

## Phase 7 — Docs, demo, CV, team onboarding

- [ ] **T-7.1** 🤝 **DR drill** — restore the base snapshot (or recreate the VM), run Ansible + bootstrap from the runbook; stopwatch the total.
  - *Acceptance:* rebuild time in DEVLOG Metrics; runbook gaps fixed.

- [ ] **T-7.2** 🤖 **Docs** — README (problem, diagram, quickstart, results, limitations incl. "host PC must be on", Tailscale limits), `architecture.md`, `runbook.md`, `security.md`, `decisions.md`.
  - *Acceptance:* a stranger can understand the system and reproduce it with their own tailnet.

- [ ] **T-7.3** 👤 **Demo assets** — screen recording/GIF of open PR → private link → update → close; Grafana screenshots into `docs/img/`.

- [ ] **T-7.4** 🤝 **`docs/cv-notes.md`** — measured bullets (real numbers), 8–10 likely interview Q&As, "what I'd improve next".
  - *Acceptance:* every number traces to the DEVLOG Metrics table.

- [ ] **T-7.5** 🤝 **Team onboarding / second repo** (depends T-4.5, T-3.5)
  - `docs/onboarding.md` ("add a new repo"): label, read-only token (also for private repos), `imagePullSecret` for private GHCR, workflow template, inviting teammates to the tailnet + `group:reviewers`, check the free-plan user cap on the official pricing page.
  - *Acceptance:* a sample second repo is onboarded by following the doc only; one real teammate opens a Tier 1 and a Tier 2 link; a non-member is denied.

---

## Phase 8 — Optional cloud variant (needs a cloud account; nothing above may depend on it)

- [ ] **T-8.1** 🤝 **Terraform (cloud): backend, network, VM, static IP** — reuse the former T-1.1–T-1.4 design; firewall 80/443 only if needed, SSH owner-only, **no 6443**; `plan` reviewed before any `apply` (🟡).
  - *Acceptance:* `terraform validate` + `tflint` clean; owner-approved `apply`; no real values in Git.

- [ ] **T-8.2** 🤖 **Run the same Ansible roles on the cloud VM** (depends T-8.1)
  - *Acceptance:* node Ready; second run = 0 changed; differences vs the local VM logged in DEVLOG.

- [ ] **T-8.3** 🤖 **Join the cloud VM to the tailnet and close public SSH** (depends T-8.2)
  - *Acceptance:* SSH works over the tailnet; port 22 not reachable on the public IP (checked from outside).

- [ ] **T-8.4** 🤝 *(optional)* **Short-lived Funnel link for recruiters** — expose one preview publicly with Funnel (limits in SPEC §4.3), basic auth recommended, remove afterwards.
  - *Acceptance:* link works from a phone on mobile data; removed after the demo; no public exposure left.

---

## Parking lot (not scheduled — see DEVLOG)
Cosign image signing + admission policy · Loki logs · scale-to-zero previews · Slack/Discord notifications · Sealed Secrets/SOPS · custom domain + wildcard cert (original v1 plan)