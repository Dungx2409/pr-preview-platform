# SPEC.md — PR Preview Platform (v2.0, private tailnet direction)

> **Status:** v2.0 · 2026-10-23 · **Owner:** Dũng
> **Role of this file:** source of truth for *what* we build and *why*. If code and SPEC disagree, stop and ask (AGENTS.md §6). Work breakdown: `TASK.md`. History/decisions/metrics: `DEVLOG.md`.
> **Supersedes v1.** v1 assumed GCP + a domain + public wildcard TLS. v2 is **local-first, private (tailnet) sharing**. See §0.

---

## 0. What changed from v1 (read once)

| Topic | v1 | v2 (this file) |
|---|---|---|
| Where it runs | GCP VM via Terraform | **Local VirtualBox VM** (Ubuntu Server) on the owner's Linux PC; GCP is an optional later variant (Phase 8) |
| Who can open previews | Anyone with the URL (public) | **Only members of the owner's Tailscale tailnet** (private) |
| URLs / TLS | `*.preview.<DOMAIN>` wildcard cert (Cloudflare DNS-01) | **Tailscale Kubernetes Operator** Ingress → `https://<name>.<tailnet>.ts.net` with valid TLS (pending spike T-2.0) |
| Environments | Per-PR only | **Two tiers:** Tier 1 shared environment, Tier 2 per-PR previews |
| Users | Owner only | Owner now; **4–5 teammates later** for group projects |
| Domain | Required | **Not needed** (none bought). Funnel/public is an optional extension |

If anything elsewhere in the repo still assumes GCP/Cloudflare/`<DOMAIN>`/public access, treat it as stale and fix it (log in DEVLOG).

---

## 1. Purpose

A self-hosted platform on the owner's own machine where code from a shared Git repo is **built automatically, deployed by GitOps onto k3s, and shared privately via a link** with teammates in the same Tailscale network:

- **Tier 1 — Shared environment:** one long-lived environment tracking `main`. A teammate changes the image tag in `values.yml` (or CI does), Argo CD pulls the new container, the shared link shows the new version.
- **Tier 2 — Per-PR previews:** every labeled Pull Request gets its **own namespace and its own link** (`pr-<N>`), updated on each push and **fully removed when the PR closes**.

**Why this project exists:** a personal portfolio project for **DevOps / Cloud intern** applications. In priority order:

1. It must **work end-to-end and be demoable** (screen recording, Grafana, README).
2. It must **show real DevOps skills:** Ansible, Kubernetes (k3s), GitOps (Argo CD), CI (GitHub Actions), private networking (Tailscale), security hardening, observability.
3. Every claim must be **measured**, not guessed.
4. The owner must **understand every part** and be able to explain it. Prefer simple over clever.
5. It must be **reusable by the owner's future 4–5 person student team** (see §6.10).

### 1.1 Non-goals (do NOT build)

- Multi-node / multi-cluster / autoscaling nodes, service mesh, custom operators.
- Public internet exposure by default (Funnel is an optional, later, per-preview extension).
- Previews for **fork** PRs (security).
- Real user data or real secrets in previews.
- Custom web UI (Grafana + Argo CD UI only).
- Multi-tenancy, SSO, billing, non-GitHub CI.
- Anything not listed here. New ideas → DEVLOG "Ideas parking lot".

### 1.2 Success targets (measure and record; never assume)

| Metric | Target | How measured |
|---|---|---|
| PR labeled → preview reachable by a tailnet member | p50 ≤ 5 min | timestamps + exporter |
| PR closed → everything gone | ≤ 3 min | `scripts/verify-teardown.sh` |
| Leaks after 20 open/close cycles | 0 | `scripts/verify-teardown.sh` |
| Rebuild platform from a fresh VM | ≤ 30 min | stopwatch in the DR drill |
| Concurrent previews that fit the VM | ≥ 5 | measured with real load |
| Tailscale free-plan headroom (user cap, tagged resources, ephemeral minutes) | no limit hit in a normal week | admin console + DEVLOG |
| Image scan gate | HIGH/CRITICAL fail the build | Trivy exit code |

---

## 2. Lifecycle (user-visible behavior)

### 2.1 Tier 1 — shared environment
1. Teammate merges code to `main` (or changes the tag in `values.yml`).
2. GitHub Actions builds the image, tags it with the **commit SHA** (never `latest`), pushes to GHCR.
3. The image tag in `values.yml` is updated (manually at first; later a CI commit — still reviewed).
4. Argo CD Application `shared-main` syncs → k3s runs the new image.
5. Everyone in the tailnet opens `https://shared.<tailnet>.ts.net`.

### 2.2 Tier 2 — per-PR previews
1. A developer opens a PR **from a branch in the same repo** and adds label `preview`.
2. Actions: test → build → Trivy → push `pr-<N>-<shortsha>` to GHCR.
3. Argo CD ApplicationSet (Pull Request generator) creates Application `preview-pr-<N>` → namespace `pr-<N>`.
4. A bot comments the **private link** on the PR (`https://pr-<N>.<tailnet>.ts.net`) and sets a Deployment status. *(Exact mechanism: §6.7, decided in T-2.0.)*
5. New push → new image tag → same link updates.
6. PR closed/merged or label removed → Application deleted → namespace and everything inside pruned; GHCR tags for that PR deleted.
7. Safety net: a reaper CronJob deletes orphan `pr-*` namespaces older than `PREVIEW_TTL_HOURS` (default 168).

---

## 3. Architecture

```
Teammate / owner (Tailscale client, member of the tailnet)
        │  https://pr-7.<tailnet>.ts.net   https://shared.<tailnet>.ts.net
        ▼
   ┌──────────── Owner's Linux PC (Intel, 24 GB RAM) ─────────────┐
   │  VirtualBox VM: Ubuntu Server (NAT + host-only adapter)      │
   │   └─ k3s (single node)                                       │
   │       ├─ Tailscale Operator → one proxy per Ingress          │
   │       ├─ Argo CD (Application shared-main + ApplicationSet)  │
   │       ├─ monitoring: Prometheus, Grafana, preview-exporter   │
   │       ├─ ns shared      : app + DB                           │
   │       ├─ ns pr-N        : app + ephemeral DB + quota + netpol│
   │       └─ reaper CronJob                                      │
   └───────────────────────────────────────────────────────────────┘
        ▲  VM only makes OUTBOUND connections
        │  (Argo CD pulls Git, kubelet pulls GHCR, Tailscale control plane)
GitHub: repo ── Actions (test → build → Trivy → push GHCR)   (NO cluster credentials in CI)
```

**Key principles**
- **Pull-based GitOps:** CI builds artifacts only; the cluster pulls desired state from Git.
- **Outbound-only networking:** no port-forwarding on the home router, no public IP needed.
- **Private by default:** only tailnet members, controlled by ACL groups.

---

## 4. Decisions

### 4.0 Locked decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **Local-first:** VirtualBox VM (Ubuntu Server, NAT + host-only) on the owner's Linux PC; record the real VM size in DEVLOG | Free, no cloud account needed, fast iteration. Host: Intel 11th-gen, 24 GB RAM. |
| D2 | **k3s single node**, version pinned | Light; ships Traefik + embedded NetworkPolicy controller |
| D3 | **Ansible** (roles `common`, `k3s`) provisions the VM; static inventory for the local VM | Core skill; idempotent; reusable on any Ubuntu host later |
| D4 | **Argo CD**: static Application for Tier 1 + **ApplicationSet (Pull Request generator)** for Tier 2, gated by label `preview` | GitOps lifecycle; label doubles as the fork-safety gate |
| D5 | **Private sharing via Tailscale** (free Personal plan; members invited to the owner's tailnet; ACL group `group:reviewers`) | No domain, no port-forwarding, private by default |
| D6 | **GitHub Actions + GHCR**; image tag = commit SHA / `pr-<N>-<shortsha>`; never `latest` | Reproducible; Argo CD detects changes |
| D7 | Secrets created **out-of-band** (env → `kubectl create secret`), never in Git | Scope control |
| D8 | Access to VM: SSH key-only from the host; k8s API (6443) reachable **only from the host-only network** | Minimal attack surface |
| D9 | Demo app = **Python (FastAPI)** + ephemeral Postgres (changeable) | Small, readable |
| D10 | Platform repo is generic enough to be reused by other repos (§6.10) | Future team use |
| D11 | **Cloud variant (GCP/Terraform/DNS) is optional Phase 8** | Owner has no GCP account/domain now |

### 4.1 Proposed — decided by spike T-2.0 (go/no-go)

| # | Decision | Status |
|---|---|---|
| D12 | **Tailscale Kubernetes Operator** (Ingress `ingressClassName: tailscale`, no Funnel) gives each environment its own `https://<name>.<tailnet>.ts.net` with valid TLS | **Proposed** — pending T-2.0 numbers |
| D13 | **Fallback if D12 is NO-GO:** install Tailscale on the VM + `tailscale serve` for one shared URL, or Traefik with `sslip.io` hostnames (self-signed/HTTP-01 TLS) inside the tailnet/LAN | Fallback only |
| D14 | **Funnel (public URL)** is an optional extension per environment, for a short demo to recruiters; never default | Optional |

### 4.2 Pinned versions
Not decided here on purpose. In **T-0.3** the agent looks up current stable releases **from official docs/release pages (never memory)**, pins them, and records them in `docs/versions.md` + DEVLOG. Applies to: k3s, Argo CD, Tailscale Operator (Helm chart), kube-prometheus-stack chart, Ansible, Python, Postgres image, Trivy, GitHub Actions (pin by version/SHA), VirtualBox/Ubuntu Server version in use.

### 4.3 Known limits of the Tailscale approach (verify in T-2.0, record real numbers)
- **Operator Ingress listens on port 443 only**; hostname for an Ingress comes from `spec.tls[].hosts[0]` (first DNS label) — verify exact field and behavior in the pinned docs. **Changing the hostname of an existing Ingress is not reliably applied** → set the right name at creation.
- **First connection can be slow or time out** while the operator provisions the TLS certificate → affects time-to-ready; measure.
- **Each exposed Ingress = one extra proxy pod and one tagged tailnet device.** Measure RAM per proxy.
- **Free Personal plan (verify on the official pricing page; numbers seen in third-party sources):** up to **6 users**, up to **3 ACL groups**, up to **50 tagged resources**, **1,000 ephemeral-resource minutes/month**, non-commercial use only. **Unknown:** whether operator proxies and ephemeral CI runners consume the 1,000-minute allowance → **measure over several hours in T-2.0**; if it blocks normal use, that is a NO-GO signal for per-PR proxies.
- **Operator cluster-ingress feature is documented as beta.**
- **Funnel (if used):** only `*.ts.net` names, only ports 443/8443/10000, TLS only, undisclosed bandwidth cap, beta; the same port cannot be both Serve and Funnel.
- Enabling tailnet HTTPS publishes machine names in public Certificate Transparency logs → use **neutral device names** (e.g. `preview-vm`), nothing sensitive.
- Everyone who needs a link must **install Tailscale and be invited** to the tailnet. The owner's PC/VM must be **on** for links to work.

---

## 5. Repository layout

```
pr-preview-platform/
├── AGENTS.md  SPEC.md  TASK.md  DEVLOG.md  README.md  Makefile
├── ansible/                 # inventory/, site.yml, roles/{common,k3s}/
├── platform/
│   ├── bootstrap/           # scripts/values for argocd, tailscale-operator, monitoring
│   ├── argocd/              # appproject-previews.yaml, application-shared.yaml, applicationset-previews.yaml
│   ├── tailscale/           # operator values, policy-snippets.json (draft for owner to paste), README
│   ├── monitoring/          # values.yaml, dashboards/, alerts/
│   └── reaper/              # cronjob.yaml
├── charts/app/              # generic Helm chart used by Tier 1 and Tier 2
├── demo-app/                # FastAPI app, Dockerfile, tests/
├── exporter/                # preview-exporter (Python)
├── scripts/                 # verify-teardown.sh, measure-ttr.sh, bootstrap.sh
├── .github/workflows/       # ci.yml, build.yml, preview.yml, preview-closed.yml
├── infra/terraform/         # (Phase 8, optional cloud variant — empty until then)
└── docs/                    # architecture.md, runbook.md, security.md, versions.md, decisions.md, onboarding.md, cv-notes.md
```

---

## 6. Component specs

### 6.1 Local VM
- VirtualBox VM, Ubuntu Server LTS, **NAT** adapter (outbound internet) + **host-only** adapter (host ↔ VM). Suggested size 8 GB RAM / 4 vCPU / 60 GB disk — **record the real values** in DEVLOG and `docs/runbook.md`.
- Take a **base snapshot** after OS install + SSH key setup (before Ansible) so the DR drill can restart from it.
- No bridged networking, no router port-forwarding.
- Document how to recreate the VM from scratch in `docs/runbook.md`.

### 6.2 Ansible (`ansible/`)
- Role `common`: apt upgrade, unattended-upgrades, SSH hardening (key-only, no root login), fail2ban, timezone, swap decision (log it).
- Role `k3s`: pinned k3s server, documented flags, kubeconfig written **outside the repo**, wait for node Ready; API reachable only on the host-only interface.
- Static inventory for the local VM (no real IP in Git if the owner prefers: use a git-ignored `inventory/local.ini` + `.example`).
- Idempotent: 2nd run = **0 changed**. `ansible-lint` clean.

### 6.3 Platform bootstrap (`platform/`)
- Install pinned Argo CD, Tailscale Operator, monitoring stack. Values files are committed; secrets are not.
- **Tailscale prerequisites (owner does these, agent drafts JSON/instructions only):** Tailscale account/tailnet; MagicDNS + HTTPS enabled; policy file with `tagOwners` for the operator and proxy tags, `group:reviewers`, an ACL/grant allowing the group to reach proxies on 443; OAuth client for the operator (scopes per current docs). Operator credentials are passed via env/Secret created out-of-band.
- Argo CD UI is **not exposed**: access via `kubectl port-forward` from the host, or via the owner's tailnet only.

### 6.4 Argo CD resources
- `AppProject previews`: allowed source repo(s) listed explicitly; allowed destinations = namespaces `shared` and `pr-*` only; cluster-resource whitelist = `Namespace` only.
- **Tier 1:** `Application shared-main` → repo path `charts/app`, revision `main`, namespace `shared`, values from `values.yml` (image tag).
- **Tier 2:** ApplicationSet (illustrative — **verify field names against the pinned Argo CD docs**):

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata: { name: previews, namespace: argocd }
spec:
  generators:
    - pullRequest:
        github:
          owner: <GITHUB_OWNER>
          repo: <APP_REPO>
          labels: [preview]
          tokenRef: { secretName: github-token, key: token }   # read-only, created out-of-band
        requeueAfterSeconds: 60
  template:
    metadata:
      name: 'preview-pr-{{number}}'
      finalizers: [resources-finalizer.argocd.argoproj.io]
    spec:
      project: previews
      source:
        repoURL: https://github.com/<GITHUB_OWNER>/<APP_REPO>.git
        targetRevision: '{{head_sha}}'
        path: charts/app
        helm:
          valuesObject:
            pr: { number: '{{number}}' }
            image: { tag: 'pr-{{number}}-{{head_short_sha}}' }
            ingress: { className: tailscale, hostname: 'pr-{{number}}' }
      destination: { server: https://kubernetes.default.svc, namespace: 'pr-{{number}}' }
      syncPolicy:
        automated: { prune: true, selfHeal: true }
        syncOptions: [CreateNamespace=true]
```
- **Verify and log in DEVLOG:** is the namespace deleted with the Application? If not, make the chart own the Namespace (pruned) and add Pod Security labels there. Are the Tailscale proxy pod and tailnet device removed when the Ingress is deleted?
- Expect a transient `ImagePullBackOff` if Argo CD syncs before CI has pushed the image; record recovery time.

### 6.5 Helm chart (`charts/app`) — used by both tiers
Templates: Namespace (if owned), Deployment (app), Service, **Ingress (`ingressClassName` and hostname from values; default `tailscale`)**, ephemeral Postgres (`postgres:<pinned>-alpine`, `emptyDir`), ResourceQuota, LimitRange, NetworkPolicy set, ServiceAccount (`automountServiceAccountToken: false`).
- Containers: non-root, read-only root FS where possible, drop all caps, no privilege escalation, requests/limits, liveness+readiness on `/healthz`.
- Namespace labels: Pod Security Standards (`enforce: baseline` minimum, aim `restricted`), `preview=true` (Tier 2), `pr=<N>`.
- NetworkPolicy: default-deny ingress+egress; allow ingress only from the Tailscale proxy pods' namespace and same namespace; egress only to DNS, same-namespace Postgres, and the internet **excluding** cluster/pod/service CIDRs and any cloud metadata address. *(k3s default pod/service CIDRs are 10.42.0.0/16 and 10.43.0.0/16 — confirm.)*
- Quota defaults (tune after measuring): ~0.5 CPU / 512 MiB requests per preview, small pod/PVC counts. `shared` may get more.

### 6.6 Demo app contract (`demo-app`)
- `GET /` → JSON `{env, pr, sha, hostname, db: "ok"|"error"}` (env vars `ENV_NAME`, `PR_NUMBER`, `GIT_SHA`).
- `GET /healthz` → 200 (no DB) · `GET /readyz` → checks DB.
- `POST /counter` increments a row in Postgres; `GET /counter` reads it (proves per-environment DB isolation).
- pytest tests; multi-stage `Dockerfile`, non-root, pinned base.

### 6.7 CI workflows
- `ci.yml` (PR/push): app lint + tests, `helm lint` + `helm template | kubeconform`, `ansible-lint`, `yamllint`, `shellcheck`, Trivy config + fs scan, gitleaks.
- `build.yml` (push to `main`): build image tag = commit SHA → Trivy image scan (fail HIGH/CRITICAL) → push to GHCR. *(Tier 1.)*
- `preview.yml` (PR events opened/synchronize/reopened/labeled; job `if`: label `preview` AND `github.event.pull_request.head.repo.full_name == github.repository`): build → Trivy → push `pr-<N>-<shortsha>` → **post/update ONE PR comment with the private link and set a Deployment status.**
- **"Is the preview up?" problem:** the GitHub runner is not in the tailnet, so it cannot poll a private URL. Options (decided in **T-2.0**, default = C):
  - **A.** Runner joins the tailnet as an *ephemeral tagged node* via the official Tailscale GitHub Action, polls, then leaves (check ephemeral-minute cost).
  - **B.** An in-cluster component (Argo CD Notifications or small Job) posts status/comment using a **narrow fine-grained token** (PR comments + deployments only).
  - **C.** CI comments the link right after pushing the image ("live once Argo CD syncs, ~1–2 min") with no health poll; time-to-ready is measured by the in-cluster exporter instead.
- `preview-closed.yml` (PR closed/unlabeled): delete GHCR tags for the PR, mark Deployment inactive, post "environment removed".
- Least-privilege `permissions:` per workflow, pinned actions, concurrency group per PR, job timeouts, **never `pull_request_target` to run PR code**.

### 6.8 Observability
- kube-prometheus-stack (or leaner), reduced retention + resource limits (the VM is shared with previews).
- `exporter/` metrics: `preview_active_total`, `preview_age_seconds{pr}`, `preview_ready_seconds{pr}` (Deployment Available transition − namespace creation), `preview_reaped_total`.
- Grafana dashboard JSON committed: active previews, time-to-ready (p50/p95), CPU/RAM per `pr-*` namespace, VM memory pressure, operator/proxy RAM.
- Alerts: VM memory > 85 %; reaper acted; (optional) Tailscale auth errors in operator logs.
- Grafana/Prometheus reachable only via port-forward or owner-only tailnet access.

### 6.9 Reaper (safety net)
CronJob lists `pr-*` namespaces, compares with open labeled PRs (GitHub API, read-only token), deletes orphans older than TTL, increments `preview_reaped_total`. Dry-run by default until verified. Must also confirm no stale Tailscale devices remain.

### 6.10 Reuse by future team projects (Tier 1 and 2 for other repos)
- ApplicationSet/Application, chart path, image repository, app repo name, hostnames are **parameters**, not hardcoded to the platform repo.
- Runbook `docs/onboarding.md` — "add a new repo": label `preview`, read-only token (private repos too), `imagePullSecret` for private GHCR images, workflow template, inviting teammates to the tailnet and ACL group.
- Team size assumption: owner + 4–5 teammates ≈ 5–6 people → must fit the Tailscale free-plan user cap (verify). If the PC is off, links die → see §13 (24/7 host).

---

## 7. Operations & resource budget
- VM memory budget (measure, do not guess): k3s + Argo CD + Tailscale Operator + monitoring leave a limited amount for previews; record headroom and max concurrent previews in DEVLOG Metrics.
- `PREVIEW_TTL_HOURS` and a **maximum concurrent previews** limit protect the VM.
- Host PC sleep/shutdown kills access: document how to shut down/start the VM cleanly and how Argo CD recovers after reboot.
- DR drill: restore the base snapshot (or recreate the VM), run Ansible + bootstrap from the runbook, record the time.

## 8. Required docs
`docs/runbook.md` (VM, up/down, debugging, rotate tokens, recover), `docs/architecture.md` (diagram + decisions), `docs/security.md` (control → how verified → result), `docs/onboarding.md` (§6.10), `docs/decisions.md` (incl. Tailscale spike write-up, pull vs push), `docs/cv-notes.md` (measured bullets, interview Q&A).

---

## 9. Security requirements (checklist)
- [ ] Previews and the shared environment are reachable **only by tailnet members** (ACL group); nothing is published to the internet by default.
- [ ] Fork PRs never get previews; label `preview` is added only by trusted maintainers.
- [ ] No secrets in Git, logs, Helm values, or image layers; gitleaks in CI.
- [ ] CI holds **no cluster credentials**; Argo CD/reaper GitHub tokens are read-only; any in-cluster write token is fine-grained and minimal.
- [ ] Tailscale OAuth client scoped per current docs; credentials only as Secrets created out-of-band; ACLs least-privilege (groups/tags, ports).
- [ ] 6443 reachable only from the host-only network; SSH key-only; no router port-forwarding.
- [ ] Isolation: namespace per environment, default-deny NetworkPolicy, no access to other namespaces or any metadata endpoint, PSS enforced, quotas set.
- [ ] Images scanned (Trivy), non-root, pinned versions.
- [ ] Neutral device/host names (Certificate Transparency exposure).
- [ ] Teammate-contributed code runs on the owner's machine → AppProject limits, quotas and NetworkPolicy are mandatory, not optional.

## 10. Phases (detailed tasks in TASK.md)
P0 Foundation → P1 Local VM + Ansible → P2 Cluster platform (**T-2.0 Tailscale spike first**) → P3 App + chart (manual deploy, then **Tier 1 shared env**) → P4 CI + GitOps lifecycle (**Tier 2 per-PR**) → P5 Hardening + cleanup → P6 Observability + metrics → P7 Docs, demo, CV, **team onboarding** → P8 Optional cloud variant.

## 11. Definition of Done (whole project)
- [ ] Tier 1: change the image tag → Argo CD syncs → a teammate in the tailnet sees the new version at the shared link.
- [ ] Tier 2: open a labeled PR → private link on the PR within target time; push updates it; close removes everything (0 leaks over 20 cycles).
- [ ] A second tailnet member (another account/device) verified access; a non-member verified **no** access.
- [ ] Platform rebuilt from a fresh VM using only the runbook; time recorded.
- [ ] Trivy gate, quotas, NetworkPolicy, PSS, fork-safety, ACL verified by scripts/tests; results in `docs/security.md`.
- [ ] Grafana dashboard with real data; README with diagram, quickstart, results, limitations; screen recording of open → link → update → close.
- [ ] `docs/onboarding.md` validated by onboarding a second sample repo.
- [ ] `docs/cv-notes.md` numbers all trace to DEVLOG Metrics.

## 12. Open questions (owner decides; agent must not assume)
| Question | Default until decided |
|---|---|
| Spike T-2.0 result: operator Ingress (D12) GO or NO-GO? Do proxies/runners eat the 1,000 ephemeral minutes? | Pending |
| "Is it up?" mechanism: A / B / C (§6.7) | C |
| Team repo public or private? (affects tokens, `imagePullSecret`) | Public |
| Actual user cap / plan limits on the Tailscale pricing page | Verify (assume ≤ 6 users) |
| VM actual size and max concurrent previews | Measure |
| When to move to a 24/7 host (§13) | When the team starts depending on it |

## 13. Phase 8 — optional cloud variant
Only if/when the owner wants a 24/7 host or the Terraform CV signal: Terraform (GCP or another cloud: network, firewall, static IP, VM), run the **same Ansible roles** on it, join it to the tailnet, and close public SSH. Needs a cloud account and billing (the owner has none now). Funnel/DNS/domain remain optional extras. Nothing in Phases 0–7 may depend on this.
