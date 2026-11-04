"""Kubernetes cluster preflight and health checks."""

from __future__ import annotations

import datetime
import json
import re
import shutil
from pathlib import Path

from scripts.preview_cli.checks import CheckResult
from scripts.preview_cli.util import load_values_config, run_command

PREVIEW_NS_REGEX = re.compile(r"^(?:preview|pr)-(\d+)$")


def _run_kubectl(args: list[str], timeout: float = 8.0) -> tuple[int, str]:
    if not shutil.which("kubectl"):
        return 127, "kubectl not found"
    try:
        res = run_command(["kubectl", *args], timeout=timeout)
        return res.returncode, res.stdout
    except Exception as exc:
        return 1, str(exc)


def check_cluster(
    repo_root: Path,
    offline: bool = False,
    skip_cluster: bool = False,
) -> list[CheckResult]:
    """Verify cluster reachability, node Ready state, platform pods, CRDs, and secrets."""
    results: list[CheckResult] = []

    if offline or skip_cluster:
        results.append(
            CheckResult(
                id="cluster.reachability",
                title="Kubernetes cluster check",
                status="SKIP",
                message="Cluster checks skipped (--offline or --skip-cluster flag provided)",
            )
        )
        return results

    if not shutil.which("kubectl"):
        results.append(
            CheckResult(
                id="cluster.reachability",
                title="Kubernetes cluster check",
                status="SKIP",
                message="kubectl CLI is not installed on host machine",
                fix="Install kubectl: https://kubernetes.io/docs/tasks/tools/",
            )
        )
        return results

    # 1. Cluster reachability & Node Ready check
    rc, out = _run_kubectl(["get", "nodes", "-o", "json", "--request-timeout=5s"])
    if rc != 0:
        results.append(
            CheckResult(
                id="cluster.reachability",
                title="Kubernetes API connectivity",
                status="FAIL",
                message="Cannot reach Kubernetes API server",
                fix=(
                    "Check if k3s is running. Set KUBECONFIG: "
                    "export KUBECONFIG=~/.kube/pr-preview.yaml. "
                    "See docs/runbook.md#1-local-vm-hardware--network-specifications"
                ),
            )
        )
        return results

    results.append(
        CheckResult(
            id="cluster.reachability",
            title="Kubernetes API connectivity",
            status="PASS",
            message="Kubernetes API server is reachable",
        )
    )

    try:
        nodes_data = json.loads(out)
        items = nodes_data.get("items", [])
        if not items:
            results.append(
                CheckResult(
                    id="cluster.node_ready",
                    title="Node Ready condition",
                    status="FAIL",
                    message="No Kubernetes nodes found in cluster",
                    fix="Verify k3s server status on target host",
                )
            )
        else:
            all_ready = True
            for node in items:
                name = node.get("metadata", {}).get("name", "unknown")
                conditions = node.get("status", {}).get("conditions", [])
                ready_cond = next(
                    (c for c in conditions if c.get("type") == "Ready"),
                    {},
                )
                if ready_cond.get("status") != "True":
                    all_ready = False
                    msg = ready_cond.get("message", "unknown")
                    results.append(
                        CheckResult(
                            id="cluster.node_ready",
                            title="Node Ready condition",
                            status="FAIL",
                            message=f"Node '{name}' is not Ready: {msg}",
                            fix=f"Inspect node: kubectl describe node {name}",
                        )
                    )
            if all_ready:
                results.append(
                    CheckResult(
                        id="cluster.node_ready",
                        title="Node Ready condition",
                        status="PASS",
                        message=f"{len(items)} node(s) verified in Ready state",
                    )
                )
    except Exception as exc:
        results.append(
            CheckResult(
                id="cluster.node_ready",
                title="Node Ready condition",
                status="WARN",
                message=f"Could not parse nodes output: {exc}",
            )
        )

    # 2. Namespace pod health checks (argocd, tailscale, monitoring, shared)
    target_namespaces = ["argocd", "tailscale", "monitoring", "shared"]
    for ns in target_namespaces:
        rc, out = _run_kubectl(["get", "pods", "-n", ns, "-o", "json", "--request-timeout=5s"])
        if rc != 0:
            results.append(
                CheckResult(
                    id=f"cluster.ns_{ns}",
                    title=f"Workloads in namespace '{ns}'",
                    status="WARN",
                    message=f"Could not list pods in namespace '{ns}'",
                    fix=f"Verify namespace exists: kubectl get ns {ns}",
                )
            )
            continue

        try:
            pod_list = json.loads(out).get("items", [])
            if not pod_list:
                results.append(
                    CheckResult(
                        id=f"cluster.ns_{ns}",
                        title=f"Workloads in namespace '{ns}'",
                        status="WARN",
                        message=f"No pods currently running in namespace '{ns}'",
                        fix=f"Bootstrap {ns} stack: make bootstrap-platform",
                    )
                )
                continue

            unhealthy: list[str] = []
            for pod in pod_list:
                pname = pod.get("metadata", {}).get("name", "")
                phase = pod.get("status", {}).get("phase", "")
                c_statuses = pod.get("status", {}).get("containerStatuses", [])
                is_restarting = any(
                    st.get("state", {}).get("waiting", {}).get("reason")
                    in ("CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull")
                    for st in c_statuses
                )
                if phase not in ("Running", "Succeeded") or is_restarting:
                    unhealthy.append(pname)

            if unhealthy:
                sample = ", ".join(unhealthy[:3])
                results.append(
                    CheckResult(
                        id=f"cluster.ns_{ns}",
                        title=f"Workloads in namespace '{ns}'",
                        status="WARN",
                        message=f"{len(unhealthy)} unhealthy pod(s) in {ns}: {sample}",
                        fix=f"Inspect pod logs: kubectl logs -n {ns} {unhealthy[0]}",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        id=f"cluster.ns_{ns}",
                        title=f"Workloads in namespace '{ns}'",
                        status="PASS",
                        message=f"All {len(pod_list)} pod(s) healthy in namespace '{ns}'",
                    )
                )
        except Exception:
            pass

    # 3. Argo CD ApplicationSet and AppProject existence
    rc_appset, _ = _run_kubectl(["get", "applicationset", "previews", "-n", "argocd"])
    if rc_appset == 0:
        results.append(
            CheckResult(
                id="cluster.applicationset",
                title="Argo CD ApplicationSet 'previews'",
                status="PASS",
                message="ApplicationSet 'previews' exists in namespace 'argocd'",
            )
        )
    else:
        results.append(
            CheckResult(
                id="cluster.applicationset",
                title="Argo CD ApplicationSet 'previews'",
                status="WARN",
                message="ApplicationSet 'previews' not found in namespace 'argocd'",
                fix="Apply: kubectl apply -f platform/argocd/applicationset-previews.yaml",
            )
        )

    rc_proj, _ = _run_kubectl(["get", "appproject", "previews", "-n", "argocd"])
    if rc_proj == 0:
        results.append(
            CheckResult(
                id="cluster.appproject",
                title="Argo CD AppProject 'previews'",
                status="PASS",
                message="AppProject 'previews' exists in namespace 'argocd'",
            )
        )
    else:
        results.append(
            CheckResult(
                id="cluster.appproject",
                title="Argo CD AppProject 'previews'",
                status="WARN",
                message="AppProject 'previews' not found in namespace 'argocd'",
                fix="Apply AppProject: kubectl apply -f platform/argocd/project-previews.yaml",
            )
        )

    # 4. Reaper CronJob
    rc_reaper, _ = _run_kubectl(["get", "cronjob", "reaper", "-n", "argocd"])
    if rc_reaper == 0:
        results.append(
            CheckResult(
                id="cluster.reaper_cronjob",
                title="Reaper CronJob",
                status="PASS",
                message="CronJob 'reaper' exists in namespace 'argocd'",
            )
        )
    else:
        results.append(
            CheckResult(
                id="cluster.reaper_cronjob",
                title="Reaper CronJob",
                status="WARN",
                message="CronJob 'reaper' not found in namespace 'argocd'",
                fix="Deploy reaper: kubectl apply -f platform/reaper/cronjob.yaml",
            )
        )

    # 5. Required in-cluster Secrets
    required_secrets = [
        ("operator-oauth", "tailscale", "Tailscale Operator OAuth secret"),
        ("github-token", "argocd", "Argo CD GitHub token secret"),
        ("shared-main-app-postgres", "shared", "Shared PostgreSQL secret"),
    ]
    for sname, sns, _sdesc in required_secrets:
        rc_sec, _ = _run_kubectl(["get", "secret", sname, "-n", sns])
        if rc_sec == 0:
            results.append(
                CheckResult(
                    id=f"cluster.secret_{sname.replace('-', '_')}",
                    title=f"In-cluster secret '{sname}' ({sns})",
                    status="PASS",
                    message=f"Secret '{sname}' exists in namespace '{sns}'",
                )
            )
        else:
            results.append(
                CheckResult(
                    id=f"cluster.secret_{sname.replace('-', '_')}",
                    title=f"In-cluster secret '{sname}' ({sns})",
                    status="FAIL",
                    message=f"Secret '{sname}' missing in namespace '{sns}'",
                    fix="Import secrets with 'make bootstrap-platform' or see README Section 7",
                )
            )

    # 6. Check lingering preview namespaces older than TTL (168 hours)
    rc_ns, out_ns = _run_kubectl(["get", "ns", "-o", "json", "--request-timeout=5s"])
    if rc_ns == 0:
        try:
            ns_items = json.loads(out_ns).get("items", [])
            now = datetime.datetime.now(datetime.timezone.utc)
            cfg = load_values_config(repo_root)
            prefix = cfg.get("namespace", {}).get("prefix", "preview")
            dyn_regex = re.compile(rf"^(?:{re.escape(prefix)}|pr|preview)-(\d+)$")

            lingering: list[str] = []
            for item in ns_items:
                ns_name = item.get("metadata", {}).get("name", "")
                if not dyn_regex.match(ns_name):
                    continue
                creation_str = item.get("metadata", {}).get("creationTimestamp")
                if creation_str:
                    c_time = datetime.datetime.fromisoformat(creation_str.replace("Z", "+00:00"))
                    age_hours = (now - c_time).total_seconds() / 3600.0
                    if age_hours > 168.0:
                        lingering.append(f"{ns_name} ({int(age_hours)}h old)")

            if lingering:
                results.append(
                    CheckResult(
                        id="cluster.lingering_namespaces",
                        title="Lingering preview namespaces",
                        status="WARN",
                        message=(
                            f"Found {len(lingering)} preview namespace(s) "
                            f"older than TTL: {', '.join(lingering)}"
                        ),
                        fix="Run 'make verify-teardown' or wait for the reaper CronJob",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        id="cluster.lingering_namespaces",
                        title="Lingering preview namespaces",
                        status="PASS",
                        message="No lingering preview namespaces older than TTL (168h)",
                    )
                )
        except Exception:
            pass

    return results
