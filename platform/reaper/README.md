# Platform Reaper (`platform/reaper/`)

> **Safety-net background worker** that periodically reconciles cluster preview environments against GitHub pull requests (SPEC §6.9, Task T-5.1).

---

## 1. Overview

The **Reaper** acts as an automated garbage collector and safety net for the PR Preview Platform:
- Queries the GitHub API for currently open pull requests labeled `preview`.
- Scans the Kubernetes cluster for namespaces matching `pr-*` and Argo CD Applications matching `preview-pr-*`.
- Identifies **orphans** (PR is closed or unlabelled, but namespace persists) and **TTL expirations** (preview age > `PREVIEW_TTL_HOURS`).
- Runs in **`DRY_RUN: "true"`** mode by default to safely report candidates without destructive changes.
- In active mode (`DRY_RUN: "false"`), deletes the Argo CD Application (invoking GitOps `resources-finalizer` cascading cleanup) and deletes the namespace directly if orphaned.
- Inspects Tailscale proxy pods in namespace `tailscale` to detect and alert on stale devices.

---

## 2. Manifests

| File | Purpose |
|---|---|
| `rbac.yaml` | `ServiceAccount: reaper`, `ClusterRole` (namespaces, pods, applications), `ClusterRoleBinding` |
| `configmap.yaml` | ConfigMap `reaper-script` embedding `reaper.py` |
| `cronjob.yaml` | CronJob `reaper` in namespace `argocd` running on schedule `*/15 * * * *` |

---

## 3. Configuration

Configured via environment variables on the CronJob container:

| Variable | Default | Description |
|---|---|---|
| `DRY_RUN` | `"true"` | When `"true"`, logs planned deletions without making API mutations. Set to `"false"` to enable active reaping. |
| `PREVIEW_TTL_HOURS` | `"24"` | Maximum preview lifetime in hours before being marked for pruning. |
| `GITHUB_REPO` | `"Dungx2409/pr-preview-platform"` | Target repository to query for open PRs. |
| `GITHUB_TOKEN` | Secret `github-token` | GitHub access token used to authenticate API queries and avoid rate limits. |

---

## 4. Verification & Testing

### Run locally via pytest
```bash
make test
```

### Trigger a manual run of the CronJob
```bash
kubectl create job --from=cronjob/reaper manual-reaper-test -n argocd
kubectl logs -n argocd job/manual-reaper-test -f
```

### Inspect Reaper logs
```bash
kubectl logs -n argocd -l app.kubernetes.io/name=reaper --tail=50
```
