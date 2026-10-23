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
