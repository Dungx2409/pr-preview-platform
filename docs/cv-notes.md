# CV Notes & Interview Preparation Guide

> A quick-reference guide containing measured resume bullet points, architectural justifications, in-depth technical interview Q&As, and future improvements for the **PR Preview Platform**.
> All performance metrics in this document trace directly to measured values in [DEVLOG.md](../DEVLOG.md#metrics).

---

## 1. Resume Bullets (Ready to Use)

Select and tailor these bullets to match the role (Platform Engineer, DevOps Engineer, Cloud Engineer, or SRE):

### Option A — Core DevOps & GitOps Focus
- **Architected and implemented a self-hosted PR Preview Platform** on a single-node k3s Kubernetes cluster using **Argo CD ApplicationSet** and **GitHub Actions**, delivering isolated on-demand ephemeral preview environments in **102s (p50)**.
- **Engineered automated teardown workflows** guaranteeing **0 resource leaks** across 20 automated test cycles, reclaiming compute, storage, and DNS proxies within **6–7s** in-cluster (**~25s** end-to-end).
- **Hardened multi-tenant workload security** utilizing Kubernetes Pod Security Standards (`baseline`), strict namespace quotas, default-deny NetworkPolicies blocking VM metadata endpoints, and non-root distroless containers.
- **Implemented zero-trust private access** via **Tailscale Kubernetes Operator**, eliminating public attack surfaces and domain requirements while providing automated valid TLS certificates (**44.2ms** TLS latency).
- **Conducted comprehensive Disaster Recovery (DR) drills**, validating an automated Ansible and shell recovery runbook achieving a **17-minute RTO** from bare OS to full multi-tenant deployment.

### Option B — Performance, Reliability & Metrics Focus
- **Built an automated GitOps preview deployment engine** that scaled to **≥ 18 concurrent environments** on an 8 GB RAM node with **51.3% memory headroom** remaining.
- **Developed a custom Prometheus exporter (`preview-exporter`)** in Python 3.10 with client-side Kubernetes discovery, scraping real-time Time-to-Ready (TTR), resource consumption, and preview lifecycles without VPN runners.
- **Designed a dual-tier deployment topology** separating a persistent Tier 1 shared staging environment (**66s** deployment on merge to `main`) from ephemeral Tier 2 per-PR previews.
- **Created a standard-library developer CLI (`make init` / `make doctor`)** executing preflight diagnostics across 8 subsystems (tools, config, secrets, GitHub, GHCR, Tailscale, host, cluster) with automated remediation.

---

## 2. 30-Second Elevator Pitch

> *"I built a lightweight, self-hosted PR Preview Platform for Kubernetes that provides ephemeral preview environments for pull requests without exposing code or cluster credentials to the public internet.*
>
> *Using a pull-based GitOps model with Argo CD ApplicationSet, the cluster reconciles pull request events from GitHub without granting CI cluster admin credentials. Environments are private-by-default using Tailscale Ingress for automated TLS and mesh-based access control. The entire platform is automated via Ansible and k3s, delivers preview URLs in under two minutes (102s p50), tears down cleanly in 6–7 seconds with zero resource leaks, and recovers from bare OS in 17 minutes."*

---

## 3. High-Frequency Technical Interview Q&A

### Q1: Why did you choose a pull-based GitOps architecture (Argo CD) over a traditional push-based CI/CD pipeline?
**Answer:**
- **Credential Isolation & Least Privilege:** In a push model, GitHub Actions runners must hold high-privilege cluster credentials (`kubeconfig` with cluster-admin rights). If a pull request runs untrusted code or a malicious dependency in CI, those cluster credentials can be leaked. With pull-based GitOps, CI only pushes container images to GHCR and comments on PRs. The cluster **pulls** state from Git; CI never receives cluster credentials.
- **Drift Detection & Self-Healing:** Argo CD continuously compares desired Git state against live cluster state. If someone manually modifies or deletes a preview deployment, Argo CD automatically reconciles and corrects the drift.
- **Declarative Lifecycle:** Preview lifecycles are modeled as declarative `Application` resources generated dynamically by the `ApplicationSet` Pull Request generator, eliminating custom imperative bash deployment scripts in CI.

---

### Q2: How do you enforce isolation between preview environments on a single Kubernetes node?
**Answer:**
We implement defense-in-depth across compute, network, and runtime layers:
1. **Namespace Isolation:** Every PR runs in an isolated namespace (`pr-<N>`).
2. **Resource Governance (ResourceQuota & LimitRange):** Each preview namespace is constrained by a `ResourceQuota` (1.5 CPU, 1.5 GiB RAM limits, max 10 pods) and a `LimitRange` with default container requests (100m CPU, 128Mi RAM). This prevents any single buggy PR from starving the host or other previews (noisy-neighbor problem).
3. **Network Isolation (NetworkPolicy):** Default-deny ingress and egress policies enforce that preview pods can only receive traffic from the Tailscale Ingress proxy and communicate with their co-located Postgres instance. Cross-namespace traffic is blocked, and egress to the hypervisor/cloud metadata endpoint (`169.254.169.254`) is explicitly denied.
4. **Pod Security Standards (PSS):** Preview namespaces enforce PSS `baseline`, prohibiting privileged containers, host networking, host PID, and host volume mounts. Containers execute as non-root users (`uid 10001`) with read-only root filesystems where applicable.

---

### Q3: Why did you use the Tailscale Kubernetes Operator instead of a public Ingress controller with wildcard Let's Encrypt certificates?
**Answer:**
- **Zero Attack Surface (Private by Default):** Previews often contain unreviewed, pre-production code with potential vulnerabilities. Exposing them to the public internet invites unauthorized probing and credential bruteforcing. Tailscale Ingress creates end-to-end encrypted mesh routes accessible only to authenticated tailnet members.
- **Cost & Operational Simplicity:** Public wildcard certificates require owning a domain and integrating with DNS providers (e.g., Cloudflare DNS-01 API keys). Tailscale provides automated valid Let's Encrypt certificates for `https://<name>.<tailnet>.ts.net` out of the box without domain fees or public DNS propagation delays.
- **Granular Role-Based Access (ACLs):** Tailscale ACL tags and groups (`group:reviewers`) allow fine-grained access control. Non-members and unauthorized teams receive instant TCP connection rejections, verified by automated security test suites.

---

### Q4: How do you prevent resource leaks and "zombie" environments when PRs are closed or merged?
**Answer:**
We employ a three-tier cleanup strategy:
1. **Primary GitOps Cascade Teardown:** When a PR is closed or its `preview` label is removed, Argo CD's ApplicationSet controller detects the event and deletes the corresponding `Application`. Because cascade deletion is configured, Kubernetes automatically deletes the child namespace, terminating deployments, services, pods, PVCs, and Tailscale proxies.
2. **CI Event Webhook (`preview-closed.yml`):** On PR closure, GitHub Actions cleans up remote container tags on GHCR (`pr-<N>-*`) and marks the GitHub Deployment environment as inactive.
3. **Automated Reaper CronJob (Safety Net):** If a GitHub webhook is dropped or an unmanaged namespace is manually deployed, an in-cluster Python `reaper` CronJob runs every 15 minutes. It discovers preview namespaces older than `PREVIEW_TTL_HOURS` (default 24h) or associated with closed GitHub PRs and purges them.
- **Verification:** An automated 20-cycle stress test script (`scripts/test-20-cycles.sh`) verified **0 leaked resources** (namespaces, PVs, Applications, or Tailscale proxy devices). In-cluster teardown completes in **6–7s** (**~25s** full CI cycle).

---

### Q5: How did you measure preview readiness, and why did you reject having CI poll the preview URL?
**Answer:**
In our architectural spike (Decision D-014), we evaluated three options:
- *Option A (CI polling via VPN):* Rejected because it requires provisioning Tailscale ephemeral auth keys inside GitHub Actions runners, burns ephemeral device minutes against the free tier cap (1,000 min/month), and tightly couples CI execution time to Kubernetes scheduling delays.
- *Option B (Wait-for-deployment in CI):* Rejected because it requires cluster admin credentials in CI, violating the pull-based security model.
- *Option C (Async Notification + In-Cluster Exporter) [Selected]:* GitHub Actions comments on the PR immediately with the predictable URL upon pushing the container image. An in-cluster Prometheus exporter (`preview-exporter`) queries the Kubernetes API directly, tracks container ready states and Ingress TLS endpoints, and calculates real Time-to-Ready (TTR).
- **Result:** Median (p50) TTR was measured at **102s (1m 42s)** from PR label event to HTTP 200 ready.

---

### Q6: How are secrets managed securely across the platform without committing them to Git?
**Answer:**
- **Zero Secrets in Repository:** The Git repository contains zero secrets, tokens, or private keys (strictly verified by `gitleaks` pre-commit hooks and CI scans).
- **Out-of-Band Disaster Recovery Store:** Required initial secrets (Tailscale OAuth credentials, GitHub token, Postgres password) are rendered to `~/.config/pr-preview/dr-secrets/` with strict POSIX permissions (`0700` directory, `0600` files) via `make init`.
- **Runtime Secret Injection:** Kubernetes `Secret` manifests are created out-of-band during initial cluster bootstrap (`make bootstrap`) or restored via `scripts/dr-restore.sh`.
- **Secret Redaction:** The CLI tooling (`scripts/preview_cli/util.py`) implements regex-based token masking that redacts PATs, OAuth keys, and passwords before emitting error messages, terminal logs, or `--json` outputs.

---

### Q7: What was your Disaster Recovery (DR) drill process and what key lessons did you learn?
**Answer:**
- **Process:** We performed a full DR recovery drill (Task T-7.1) by reverting the host VM to a blank base OS snapshot, executing Ansible provisioning, and running the automated bootstrap sequence (`scripts/dr-restore.sh`).
- **Recovery Time Objective (RTO):**
  - **17 minutes** with pre-cached container images and charts.
  - **39m 50s** cold scratch recovery from bare OS with live binary and container downloads.
- **Key Discovery (Gotcha):** VirtualBox hardware snapshot regression: Restoring the initial snapshot silently downgraded VM RAM from 8 GB to 2 GB because the snapshot was captured before memory reconfiguration. This caused heavy swap thrashing and API timeouts. We resolved this by embedding an automated VM hardware validation step (`VBoxManage modifyvm --memory 8192`) into the runbook and recovery script.

---

### Q8: How did you calculate node capacity and maximum concurrent preview environments?
**Answer:**
We performed empirical resource budgeting based on real Prometheus and `kubectl top` measurements:
- **Node Resources:** Single VM with 8 GB (7,424 MB usable) RAM and 4 vCPUs.
- **Platform Overhead:**
  - Base OS & k3s runtime: ~1,657 MB used post-install (**77.7% free**).
  - Argo CD stack (5 pods): **118 MiB** (Controller: 24 MiB, Repo Server: 21 MiB, Server: 44 MiB, Redis: 5 MiB).
  - Monitoring stack (Prometheus, Grafana, Alertmanager, Node Exporter, KSM, Exporter): **~869 MiB**.
  - Tailscale Operator: ~20–26 MiB baseline.
- **Available Headroom:** Post-monitoring baseline leaves **3,805 MB (51.3%) free RAM**.
- **Per-Preview Footprint:** Each preview environment requests ~150 MiB (FastAPI app: ~30 MiB, ephemeral Postgres: ~45 MiB, Tailscale Ingress proxy pod: **~16.5 MiB**).
- **Concurrency Limit:** Reserving a 1 GB safety buffer for host OS spikes and compilation tasks, the node comfortably hosts:
  $$\frac{3,805\text{ MB} - 1,000\text{ MB}}{150\text{ MB/preview}} \approx \mathbf{18\text{ concurrent preview environments}}.$$

---

### Q9: Can you describe an unexpected technical problem you diagnosed and solved during this project?
**Answer:**
*(Pick one of these two real production gotchas from `DEVLOG.md`):*

- **Story A — Grafana Distroless Startup Probe Race Condition:**
  - *Symptom:* Upgrading to Grafana v13 distroless caused the Grafana pod to crash in `CrashLoopBackOff` on every node restart due to liveness probe failure (`connection refused: 3000`).
  - *Investigation:* Profiling container startup revealed that Grafana v13 spawns 15 bundled data source and app plugins concurrently as separate child processes. Under restricted CPU limits (`200m`), plugin initialization spiked CPU and took > 120 seconds, exceeding default probe timeouts (`initialDelaySeconds: 60`).
  - *Resolution:* Tuned CPU limits to `500m`, memory to `512Mi`, and adjusted probe settings (`initialDelaySeconds: 120`, `failureThreshold: 20`). Once initialized, steady-state CPU dropped to < 20m.

- **Story B — Argo CD Pull Request Generator Short SHA Mismatch:**
  - *Symptom:* Preview pods failed with `ImagePullBackOff` because container images pushed by CI were not found.
  - *Investigation:* Argo CD ApplicationSet's `{{head_short_sha}}` template variable defaults to an **8-character** hex string (e.g. `b2f4477f`), whereas standard git commands and GitHub Actions naive expressions produce a **7-character** short SHA (`b2f4477`).
  - *Resolution:* Updated the CI build workflow (`.github/workflows/preview.yml`) to push both 7-character and 8-character image tags (`pr-<N>-<sha7>` and `pr-<N>-<sha8>`), ensuring reliable compatibility without hardcoding fragile git parsing logic.

---

### Q10: What is the architectural difference between Tier 1 (Shared) and Tier 2 (Previews)?
**Answer:**
- **Tier 1 (Shared Staging):** A long-running baseline environment deployed in namespace `shared` accessible at `https://shared.<tailnet>.ts.net`. It tracks the `main` branch. When PRs are merged, `build.yml` updates the container image tag in `values.yaml`, and Argo CD syncs the deployment in **66s**. It acts as a shared integration and smoke-testing target.
- **Tier 2 (Per-PR Previews):** Ephemeral, dynamic environments deployed in isolated namespaces (`pr-<N>`) accessible at `https://pr-<N>.<tailnet>.ts.net`. They are instantiated only when PRs have the `preview` label, run ephemeral database instances, and are destroyed immediately upon PR closure.

---

## 4. Architectural Trade-offs & "What I'd Improve Next"

When asked *"What are the limitations of this project and how would you evolve it?"*, discuss these concrete engineering trade-offs:

| Current Design Choice | Why We Did It | Production Evolution (Next Steps) |
|---|---|---|
| **Single-Node k3s on Local VM** | Zero cloud cost during development, rapid local iteration, fits inside 8 GB VM. | Migrate to managed cloud Kubernetes (EKS / GKE) using Terraform IaC (Phase 8 template) with multi-node node pools. |
| **Tailscale Ingress (Private Mesh)** | Zero domain fees, instant TLS, eliminates public attack surface for unreviewed PR code. | Add optional **Tailscale Funnel** with basic auth for external client/recruiter demos without requiring them to join the tailnet. |
| **Ephemeral In-Cluster Postgres** | Lightweight (45 MiB), zero state pollution between PRs, fast provisioning. | Implement **Database Branching** (e.g. Neon, Supabase, or copy-on-write CSI snapshots) to seed previews with realistic sanitized production schemas. |
| **Always-On Preview Pods** | Simplest architecture; immediate response times without cold starts. | Introduce **Scale-to-Zero** using KEDA or Knative to sleep preview pods after 30 minutes of inactivity, increasing concurrency from 18 to 50+ previews. |
| **Local Admin Secret Management** | POSIX permissions (`0700`/`0600`) out-of-band without external SaaS dependencies. | Integrate **External Secrets Operator** (ESO) backed by HashiCorp Vault, AWS Secrets Manager, or Google Secret Manager. |

---

## 5. Metrics Verification Cross-Reference

Every number cited in this document is verified against the project record:

| Claimed Metric | Measured Value | Source in Repository |
|---|---|---|
| PR labeled → URL healthy | **102s (1m 42s)** | [DEVLOG.md](../DEVLOG.md#metrics) (T-4.4, PR #26) |
| PR closed → teardown | **6–7s** (cluster) / **~25s** (CI) | [DEVLOG.md](../DEVLOG.md#metrics) (T-4.5/T-4.6, PR #28) |
| DR rebuild time | **17 min** (cached) / **39m 50s** (cold) | [DEVLOG.md](../DEVLOG.md#metrics) (T-7.1 DR Drill) |
| Teardown leaks (20 cycles) | **0 leaks** | [DEVLOG.md](../DEVLOG.md#metrics) (T-4.6, `test-20-cycles.sh`) |
| Argo CD stack RAM footprint | **118 MiB** (5 pods) | [DEVLOG.md](../DEVLOG.md#metrics) (T-2.3) |
| Tailscale proxy RAM footprint | **~16.5 MiB / proxy pod** | [DEVLOG.md](../DEVLOG.md#metrics) (T-2.0 Spike) |
| Subsequent TLS request latency | **44.2 ms** | [DEVLOG.md](../DEVLOG.md#metrics) (T-2.0 Spike) |
| Tailscale Ephemeral Minutes used | **0 min** (tagged stateful nodes) | [DEVLOG.md](../DEVLOG.md#metrics) (T-2.0 Spike) |
| Node RAM headroom post-monitoring| **51.3% free** (3,805 MB available) | [DEVLOG.md](../DEVLOG.md#metrics) (T-6.1) |
| Max concurrent preview capacity | **≥ 18 environments** | [DEVLOG.md](../DEVLOG.md#metrics) (T-6.1) |
| Tier 1 deploy on merge to main | **66s** | [DEVLOG.md](../DEVLOG.md#metrics) (T-3.5, PR #18) |
