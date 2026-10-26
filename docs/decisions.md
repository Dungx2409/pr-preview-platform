# Architecture Decisions

This document records architectural spikes, evaluated alternatives, and binding design decisions for the PR Preview Platform.

---

## ADR-001: Private Ingress for Ephemeral Previews (Tailscale Operator vs. Fallback D13)

- **Status:** **GO** (Decided in Spike T-2.0, 2026-10-23)
- **Decider:** Dũng Lương (Owner) & Antigravity (Agent)
- **Consulted:** SPEC §4.1 (D12 vs D13), SPEC §4.3, SPEC §6.7

### 1. Context & Problem Statement
Each PR preview requires an isolated, secure, private HTTPS endpoint accessible to team reviewers without exposing internal workloads to the public internet. We evaluated:
- **Option D12 (Proposed):** Tailscale Kubernetes Operator (`ingressClassName: tailscale`), providing dedicated `https://<pr-name>.<tailnet>.ts.net` endpoints with automatic MagicDNS and valid Let's Encrypt TLS certificates.
- **Option D13 (Fallback):** Host-level `tailscale serve` / Traefik with `sslip.io` wildcards and self-signed or HTTP-01 certificates.

### 2. Empirical Spike Measurements (T-2.0)

All measurements conducted on the local single-node k3s cluster (`v1.36.5+k3s1`, Ubuntu 24.04 VM, 4 GB RAM, 2 vCPUs) using Tailscale Operator `v1.104.2`:

| Metric | Measured Value | Notes |
|---|---|---|
| **Operator Footprint** | CPU: 3m (idle) / 26m (sync) · RAM: 20–26 MiB | Stable across 1 to 5 Ingresses |
| **Proxy Pod Footprint** | CPU: 1m (idle) / 14m (ACME sync) · RAM: 16–17 MiB per proxy | Exactly 1 StatefulSet + 1 Pod per Ingress |
| **RAM at 1 Ingress** | ~39 MiB total (Operator + 1 Proxy) | `kubectl top pod -n spike-ts` |
| **RAM at 3 Ingresses** | ~75 MiB total (Operator + 3 Proxies) | Linear scaling: ~16.5 MiB per preview |
| **RAM at 5 Ingresses** | ~109 MiB total (Operator + 5 Proxies) | Fits easily within VM 4 GB memory budget |
| **First TLS Issuance Delay** | **36s – 38s** | Let's Encrypt DNS-01 via Tailscale control plane |
| **Subsequent Request Latency**| **44.2 ms** total (DNS: 1.5ms, Connect: 2.7ms, TLS: 42.8ms) | HTTP/2 over Tailscale WireGuard mesh |
| **Teardown & Cleanup** | Immediate (< 3s) | Pod, StatefulSet, and Tailnet node revoked cleanly |
| **Recreate Same Hostname** | Identical hostname reused | Node was cleanly revoked, no `-1` suffix added |
| **Dynamic Hostname Rename** | Supported (~36s update) | `tailscaled config watch` reloads, re-authenticates & re-certs |
| **Tailscale Quotas** | 5 nodes used / 50 tagged devices allowed | 0 ephemeral-runner minutes consumed |

### 3. "Is the Preview Up?" Evaluation (SPEC §6.7)

| Option | Approach | Quota Impact | Security / Simplicity | Recommendation |
|---|---|---|---|---|
| **A** | CI runner joins tailnet via GitHub Action, polls URL | Consumes ephemeral runner minutes (1,000 min/mo limit) | Heavy CI dependency; needs tailnet authkey in GitHub Secrets | ❌ Reject |
| **B** | In-cluster Job / Argo notification posts status to PR | Zero tailnet quota | Requires GitHub token with PR comment permissions in cluster | ⚠️ Secondary option |
| **C** (SPEC Default) | CI posts comment right after image push; exporter tracks ready metric | **Zero** tailnet quota | **Highest security:** CI holds no cluster credentials, zero VPN dependencies | ✅ **Selected** |

### 4. Comparison: D12 vs. Fallback D13

| Dimension | D12: Tailscale Operator | D13: Traefik + sslip.io / Single Serve |
|---|---|---|
| **Domain / Certs** | Native `https://<pr>.<tailnet>.ts.net` with valid Let's Encrypt TLS | Self-signed certs (browser security warnings) or complex HTTP-01 |
| **Per-PR Isolation** | Strong: each Ingress gets an independent proxy pod with ACL tags | Shared proxy; URL path or host routing in one shared ingress |
| **User Identity** | Passes `Tailscale-User-Login` and `Tailscale-User-Name` headers to app | No built-in user identity propagation |
| **Resource Overhead**| ~16.5 MiB RAM per active preview | ~0 extra pods, but high configuration coupling |
| **Operational Simplicity** | Declarative GitOps via standard Kubernetes Ingress manifests | Custom reverse-proxy routing scripts and DNS hacks |

### 5. Identified Gotchas & Mitigations

1. **First-connection TLS delay (36–38s):**
   * *Mitigation:* The PR comment explicitly indicates "Environment provisioning: ready in ~1–2 minutes" (Option C). Reviewers typically open PR previews minutes after push.
2. **Operator finalizer on Ingress deletion:**
   * *Gotcha:* If the operator is deleted *before* the Ingresses, Ingresses remain stuck in `Terminating` due to `tailscale.com/finalizer`.
   * *Mitigation:* In normal GitOps workflows, Argo CD prunes child Ingress resources before any platform components are removed. Document manual finalizer removal in `docs/runbook.md`.

### 6. Decision & Next Steps
- **Verdict: GO.**
- Adopt **D12** (Tailscale Kubernetes Operator) as the standard ingress mechanism for Tier 1 (`shared`) and Tier 2 (`pr-*`) environments.
- Proceed to **T-2.1** (Tailscale Operator repo-managed install under `platform/tailscale/`).

---

## ADR-002: Infrastructure Hosting — Local VirtualBox VM with k3s vs. Managed Cloud Kubernetes

- **Status:** **Accepted** (Decided in T-0.1 / SPEC §4.1 D1b)
- **Decider:** Dũng Lương (Owner)
- **Consulted:** SPEC §1, §4.1

### 1. Context & Problem Statement
Hosting a continuous PR preview platform requires a Kubernetes runtime. We evaluated:
- **Option A (Managed Cloud K8s - GKE / EKS):** Hosted control plane with public cloud load balancers.
- **Option B (Local Hypervisor VM with k3s):** Ubuntu Server 24.04 VM running single-node k3s managed via Ansible on VirtualBox.
- **Option C (Local Containerized K8s - Kind / Minikube):** Running directly on the developer desktop OS.

### 2. Comparison & Trade-Offs

| Dimension | Option A (Cloud GKE/EKS) | Option B (VirtualBox + k3s) | Option C (Kind / Minikube) |
|---|---|---|---|
| **Cost** | $70–$140+/mo for control planes, nodes, and LBs | **$0/mo** (runs on existing local hardware) | $0/mo |
| **Reproducibility** | Terraform-driven, but cloud resource cleanup required | **Instant snapshot restore** (`VBoxManage snapshot restore`) | ephemeral container recreate |
| **Production Realism**| High | **High:** Dedicated Linux VM with systemd, SSH, and host-only adapter | Low: Docker-in-Docker networking quirks |
| **Security Surface** | Public IPs, cloud VPCs, IAM credentials | **Isolated host-only network** (`192.168.56.0/24`) | Shared with host OS processes |

### 3. Decision
Adopt **Option B (VirtualBox VM + single-node k3s + Ansible)**. It satisfies the portfolio project goal of zero cloud recurring costs while maintaining 100% production-grade Linux VM isolation and snapshot-based disaster recovery.

---

## ADR-003: Deployment Model — Pull-Based GitOps (Argo CD) vs. Push-Based CI/CD

- **Status:** **Accepted** (Decided in T-2.2 / SPEC §4.1 D2)
- **Decider:** Dũng Lương (Owner)
- **Consulted:** SPEC §6.4, §9

### 1. Context & Problem Statement
Preview environments must be provisioned automatically when a PR is created or updated.
- **Option A (Push-Based CI/CD):** GitHub Actions runners connect directly to the Kubernetes API server using stored `KUBECONFIG` credentials to run `kubectl apply` or `helm install`.
- **Option B (Pull-Based GitOps):** Argo CD runs inside the cluster, polls the Git repository for open PRs via the ApplicationSet PR Generator, and pulls manifests into the cluster.

### 2. Decision & Security Justification
Adopt **Option B (Pull-Based GitOps via Argo CD)**.
- **Credential Hygiene:** CI runners hold **zero cluster credentials**. Compromising a CI workflow or third-party GitHub Action cannot result in cluster takeover.
- **Network Inaccessibility:** The Kubernetes API server remains bound to the private host-only adapter (`192.168.56.10:6443`), requiring no public ingress or VPN tunnels for CI runners.
- **Self-Healing & Drift Detection:** Argo CD continuously reconciles out-of-band drift, ensuring preview environments strictly mirror Git declarations.

---

## ADR-004: Ephemeral Database Isolation — Per-PR PostgreSQL vs. Shared Database

- **Status:** **Accepted** (Decided in T-3.1 / SPEC §4.1 D5)
- **Decider:** Dũng Lương (Owner)
- **Consulted:** SPEC §6.5

### 1. Context & Problem Statement
Full-stack preview environments require database persistence for testing migrations, schemas, and API features.
- **Option A (Shared Multi-Tenant Database):** One central PostgreSQL instance with dynamic databases or schemas per PR (e.g., `db_pr_24`).
- **Option B (Dedicated Ephemeral Container per PR):** A lightweight `postgres:16-alpine` container running inside each `pr-<N>` namespace.

### 2. Comparison & Decision
Adopt **Option B (Dedicated Ephemeral Container per PR)**.
- **Zero Schema Interference:** Risky database migrations, table drops, or destructive operations in PR previews cannot impact other reviewers or the Tier 1 baseline app.
- **Resource Footprint:** Postgres 16 on Alpine consumes only ~28–32 MiB idle RAM, easily fitting within the VM's 8 GB budget for up to 10 simultaneous previews.
- **Clean Teardown:** Ephemeral storage uses Kubernetes `emptyDir`. Deleting the namespace instantly frees all disk space with zero orphaned volumes.

---

## ADR-005: Dual-Layer Teardown & Leak Prevention

- **Status:** **Accepted** (Decided in T-4.5 / T-4.6 / SPEC §4.1 D6)
- **Decider:** Dũng Lương (Owner)
- **Consulted:** SPEC §6.4, §8

### 1. Context & Problem Statement
On a single-node cluster, orphaned preview environments quickly exhaust memory and CPU. Relying solely on a single teardown mechanism introduces failure points (e.g., missed webhook events, runner timeouts, manual PR closes).

### 2. Decision
Implement a **dual-layer teardown architecture**:
1. **Fast-Path (Event-Driven):** GitHub Actions workflow (`preview-teardown.yml`) triggers on `pull_request: [closed]`, immediately deleting the GHCR image and removing the `preview` label. Argo CD prunes the application within 6–7 seconds.
2. **Slow-Path Safety Net (In-Cluster Reaper CronJob):** An autonomous Python script runs every 15 minutes inside the cluster, querying the GitHub API. It detects and terminates:
   - Orphaned namespaces whose PR was closed without triggering CI.
   - Stale previews that exceeded maximum TTL (24 hours).
   - Dangling Tailscale proxy pods whose parent preview application was removed.

---

## ADR-006: Observability Architecture — In-Cluster preview-exporter vs. Blackbox Poller

- **Status:** **Accepted** (Decided in T-6.1 / T-6.2 / SPEC §4.1 D7)
- **Decider:** Dũng Lương (Owner)
- **Consulted:** SPEC §6.8

### 1. Context & Problem Statement
The platform requires metrics on active preview count, time-to-ready duration, and reaped environments for Grafana dashboards and alerts.
- **Option A (External Blackbox Poller):** CI runner or external SaaS joins the Tailnet to periodically HTTP GET preview URLs.
- **Option B (Native In-Cluster Exporter):** A lightweight Python daemon (`preview-exporter`) scraping Kubernetes API events and Application CRDs directly inside the cluster, exposing `/metrics` for Prometheus.

### 2. Decision
Adopt **Option B (In-Cluster preview-exporter)**.
- **Zero VPN Quota Consumption:** Avoids burning Tailscale ephemeral runner quotas (1,000 min/mo free tier limit).
- **Direct Event Aggregation:** Computes exact time-to-ready by observing Kubernetes timestamps (`creationTimestamp` to Pod Ready condition) rather than polling over network latency.
- **Cloud-Native Prometheus Integration:** Deployed with standard Kubernetes `ServiceMonitor` and scraped natively by `kube-prometheus-stack`.

