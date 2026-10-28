# Runbook: Local VM Operations & Disaster Recovery (`docs/runbook.md`)

> **Scope:** Standard Operating Procedures (SOP) for managing, running, and recreating the local VirtualBox VM hosting the k3s cluster (SPEC v2.0 §6.1, Task T-1.0).

---

## 1. Local VM Hardware & Network Specifications

The platform runs on a local single-node VirtualBox VM hosted on the owner's Linux machine (Intel 11th-gen, 24 GB RAM):

| Property | Value | Notes |
|---|---|---|
| **VM Name** | `devops-server` | Defined in VirtualBox |
| **Guest OS** | Ubuntu Server 24.04 LTS (64-bit) | Minimal server install, no GUI |
| **vCPU** | 2 | Dedicated cores |
| **RAM** | 8192 MB (8 GB) | Sufficient for k3s, Argo CD, operator, and 5+ previews |
| **Disk** | 25.6 GB VDI (dynamic) | Boot disk mounted on `/` |
| **Adapter 1 (NAT)** | DHCP | Grants outbound internet access for package updates, image pulls, GitOps sync |
| **NAT Port Forward** | `127.0.0.1:2222` → guest `22` | Fallback emergency SSH access via localhost |
| **Adapter 2 (Host-Only)** | `vboxnet0` (Static IP) | Host: `192.168.56.1/24`, Guest: `192.168.56.10/24` |
| **k8s API Endpoint** | `https://192.168.56.10:6443` | Reachable **only** from the host machine via host-only network |
| **Default SSH User** | `vboxuser` | Key-based authentication via `~/.ssh/id_ed25519` |

---

## 2. Day-to-Day Operations (Headless CLI)

Manage the VM without opening the VirtualBox GUI:

### Start VM (Headless)
```bash
VBoxManage startvm "devops-server" --type headless
```

### Check VM Status
```bash
VBoxManage list runningvms
```

### Graceful Shutdown (ACPI)
```bash
VBoxManage controlvm "devops-server" acpipowerbutton
```

### Save State (Fast pause / resume)
```bash
VBoxManage controlvm "devops-server" savestate
```

### SSH into the VM from Host
```bash
ssh -i ~/.ssh/id_ed25519 vboxuser@192.168.56.10
```

---

## 3. Snapshot Management

Snapshots allow instant recovery during Disaster Recovery (DR) drills or before risky Ansible changes:

### Current Snapshots Tree
- `clean-os-ssh-ready` (Initial clean OS, SSH port forwarding 2222 configured)
  - `base vm` (Base operating system, static IP `192.168.56.10`, SSH key-only ready)
    - `k3s-ok` (k3s server installed and node Ready)

### Take a New Snapshot
Always power off or pause the VM before taking a clean disk snapshot:
```bash
VBoxManage snapshot "devops-server" take "<snapshot-name>" --description "<purpose>"
```

### Restore to Base Snapshot (Disaster Recovery Drill)
```bash
VBoxManage controlvm "devops-server" poweroff
VBoxManage snapshot "devops-server" restore "base vm"
VBoxManage startvm "devops-server" --type headless
```

---

## 4. Recreate VM From Scratch (Step-by-Step)

A second engineer can reproduce the exact VM environment from scratch using the steps below:

### Step 1: Create VirtualBox Network & VM
Ensure host-only interface `vboxnet0` exists on the Linux host:
```bash
VBoxManage hostonlyif create 2>/dev/null || true
VBoxManage hostonlyif ipconfig vboxnet0 --ip 192.168.56.1 --netmask 255.255.255.0
```

Create and configure the VM:
```bash
VBoxManage createvm --name "devops-server" --ostype "Ubuntu_64" --register
VBoxManage modifyvm "devops-server" --memory 8192 --cpus 2 --vram 16
VBoxManage modifyvm "devops-server" --nic1 nat --natpf1 "SSH,tcp,127.0.0.1,2222,,22"
VBoxManage modifyvm "devops-server" --nic2 hostonly --hostonlyadapter2 vboxnet0
```

Attach a 25 GB storage drive and mount the Ubuntu Server ISO:
```bash
VBoxManage createmedium disk --filename "$HOME/VirtualBox VMs/devops-server/devops-server.vdi" --size 25600
VBoxManage storagectl "devops-server" --name "SATA" --add sata --controller IntelAhci
VBoxManage storageattach "devops-server" --storagectl "SATA" --port 0 --device 0 --type hdd --medium "$HOME/VirtualBox VMs/devops-server/devops-server.vdi"
```

### Step 2: Install Ubuntu Server 24.04 LTS
1. Start the VM, boot from the ISO, and complete minimal server installation.
2. Username: `vboxuser`.
3. Enable OpenSSH server during installation.

### Step 3: Configure Host-Only Static IP (Netplan)
Inside the VM, edit `/etc/netplan/01-netcfg.yaml` (or existing netplan file):
```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      dhcp4: true
    enp0s8:
      addresses:
        - 192.168.56.10/24
```
Apply configuration:
```bash
sudo netplan apply
```

### Step 4: Configure SSH Key-Only Authentication
From the host machine, copy your public SSH key:
```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub -p 2222 vboxuser@127.0.0.1
```
Verify direct connection over the host-only IP:
```bash
ssh -i ~/.ssh/id_ed25519 vboxuser@192.168.56.10
```

### Step 5: Save Base Snapshot
Power off the VM and capture the base state:
```bash
VBoxManage controlvm "devops-server" acpipowerbutton
VBoxManage snapshot "devops-server" take "base vm" --description "Base OS, static IP 192.168.56.10, SSH key ready"
```
The VM is now ready for Ansible automation (Phase 1, T-1.5).

---

## 5. Platform Bootstrap & Ingress (Phase 2)

### Install Managed Tailscale Operator
The Tailscale Kubernetes Operator is managed via Helm chart `tailscale/tailscale-operator` (`1.104.2`) under namespace `tailscale`.

1. Create the `operator-oauth` secret out-of-band:
```bash
KUBECONFIG=~/.kube/pr-preview.yaml kubectl create namespace tailscale
KUBECONFIG=~/.kube/pr-preview.yaml kubectl create secret generic operator-oauth \
  --namespace=tailscale \
  --from-literal=client_id="<CLIENT_ID>" \
  --from-literal=client_secret="<CLIENT_SECRET>"
```

2. Execute the bootstrap script:
```bash
platform/bootstrap/install-tailscale.sh
```

3. Verify operator rollout and status:
```bash
KUBECONFIG=~/.kube/pr-preview.yaml kubectl get pods -n tailscale
```

### Manual Finalizer Cleanup (Disaster Recovery Gotcha)
If an Ingress or namespace becomes stuck in `Terminating` because the operator was uninstalled first:
```bash
KUBECONFIG=~/.kube/pr-preview.yaml kubectl patch ingress <ingress-name> -n <namespace> \
  --type=json -p='[{"op": "remove", "path": "/metadata/finalizers"}]'
```

### Install Argo CD (GitOps Engine)
Argo CD is pinned to chart `argo/argo-cd:10.10.5` (`v3.5.6`) under namespace `argocd`. UI is strictly isolated (ClusterIP only, no public or tailnet Ingress).

1. Create GitHub read-only token Secret out-of-band:
```bash
KUBECONFIG=~/.kube/pr-preview.yaml kubectl create namespace argocd --dry-run=client -o yaml | KUBECONFIG=~/.kube/pr-preview.yaml kubectl apply -f -
KUBECONFIG=~/.kube/pr-preview.yaml kubectl create secret generic github-token \
  --namespace=argocd \
  --from-literal=token="<GITHUB_PAT>"
```

2. Execute bootstrap script:
```bash
platform/bootstrap/install-argocd.sh
```

3. Access UI locally via Port-Forward (Host only):
```bash
KUBECONFIG=~/.kube/pr-preview.yaml kubectl port-forward svc/argocd-server -n argocd 8080:443
```
Open `https://localhost:8080` in your host browser. Login as `admin`.

### AppProject previews (Tenant Isolation)
The `previews` AppProject (`platform/argocd/project-previews.yaml`) enforces least-privilege boundaries:
- Source repository restricted strictly to `https://github.com/Dungx2409/pr-preview-platform.git`.
- Destination namespaces restricted strictly to `shared` and `pr-*`.
- Cluster-scoped resources restricted exclusively to `Namespace`.

Apply or verify AppProject:
```bash
KUBECONFIG=~/.kube/pr-preview.yaml kubectl apply -f platform/argocd/project-previews.yaml
KUBECONFIG=~/.kube/pr-preview.yaml kubectl get appproject previews -n argocd
```

### 5.3 Switching Project / Centralized Configuration (`values.yaml`)

The platform's target workload is parameterized via the root [`values.yaml`](../values.yaml).

**Rule: "Đổi dự án = sửa `values.yaml`, commit, Argo sync"**

```yaml
repo:
  url: "https://github.com/Dungx2409/pr-preview-platform.git"
  label: "preview"
app:
  name: "demo-app"
  image: "ghcr.io/dungx2409/demo-app"
  port: 8000
  healthcheck: "/healthz"
namespace:
  prefix: "preview"
```

**Step-by-Step Procedure to Switch to a New Project:**
1. **Modify `values.yaml`:**
   - Update `repo.url` to the new project's Git URL.
   - Update `app.name`, `app.image`, `app.port`, and `app.healthcheck`.
   - Update `namespace.prefix` if running in parallel with existing previews to avoid collisions.
2. **Update AppProject Whitelist (if switching Git repositories):**
   - In `platform/argocd/project-previews.yaml`, add the new `repo.url` under `spec.sourceRepos` to satisfy tenant isolation (SEC-14).
3. **Commit & Push:**
   ```bash
   git add values.yaml platform/argocd/project-previews.yaml
   git commit -m "chore: switch platform project in values.yaml"
   git push origin main
   ```
4. **Argo CD Sync:**
   Argo CD reconciles the ApplicationSet within 30 seconds. All subsequent PR previews automatically adopt the new application image, port, and health check.

---

## 6. Credential & Secret Rotation Procedures (SOP)

This section provides Standard Operating Procedures (SOP) for periodic rotation and emergency revocation of all platform credentials per SPEC §9 and TASK T-5.3.

### 6.1 GitHub Personal Access Token (`github-token` in `argocd`)

The `github-token` secret is consumed by two critical GitOps components:
1. **Argo CD ApplicationSet Controller:** Polls GitHub API (`GET /repos/:owner/:repo/pulls`) to generate preview applications.
2. **Reaper CronJob:** Polls GitHub API to reconcile active namespaces against open PRs to delete orphans and enforce TTLs.

#### Least-Privilege Scope Requirements:
- **Fine-Grained Personal Access Token (Recommended):**
  - **Repository Access:** Selected repositories only (`pr-preview-platform`).
  - **Permissions:**
    - `Pull requests`: Read-only.
    - `Contents`: Read-only.
- **Prohibited Permissions:** Never grant `Admin`, `Delete repo`, `Workflows`, or any `Write` scopes.

#### Step-by-Step Rotation:
1. **Generate New Token:**
   - Go to GitHub -> Settings -> Developer Settings -> Personal Access Tokens -> Fine-grained tokens.
   - Click **Generate new token**. Set Name: `pr-preview-argocd-reaper-token-<YYYYMMDD>`, Expiration: 90 days.
   - Select repository: `Dungx2409/pr-preview-platform`.
   - Set Permissions: `Pull requests: Read-only`, `Contents: Read-only`. Copy the new token.

2. **Update Kubernetes Secret (Zero-Downtime Atomic Replacement):**
   ```bash
   KUBECONFIG=~/.kube/pr-preview.yaml kubectl create secret generic github-token \
     --namespace=argocd \
     --from-literal=token="<NEW_TOKEN>" \
     --dry-run=client -o yaml | KUBECONFIG=~/.kube/pr-preview.yaml kubectl apply -f -
   ```

3. **Restart Consumers (Seamless Pick-up):**
   ```bash
   # Restart ApplicationSet controller to reload in-memory cache
   KUBECONFIG=~/.kube/pr-preview.yaml kubectl rollout restart deployment argocd-applicationset-controller -n argocd
   KUBECONFIG=~/.kube/pr-preview.yaml kubectl rollout status deployment argocd-applicationset-controller -n argocd
   ```
   *Note:* The Reaper CronJob reads the secret fresh on every run (`*/15 * * * *`), so it automatically adopts the new token on its next execution.

4. **Verify Live Operation:**
   ```bash
   # Verify ApplicationSet controller is polling GitHub without errors
   KUBECONFIG=~/.kube/pr-preview.yaml kubectl logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller --tail=30 | grep -E -i "error|github|reconciliation"

   # Trigger an on-demand Reaper run to verify GitHub API connectivity
   KUBECONFIG=~/.kube/pr-preview.yaml kubectl create job --from=cronjob/reaper reaper-rotation-verify -n argocd
   KUBECONFIG=~/.kube/pr-preview.yaml kubectl wait --for=condition=complete job/reaper-rotation-verify -n argocd --timeout=60s
   KUBECONFIG=~/.kube/pr-preview.yaml kubectl logs -n argocd job/reaper-rotation-verify
   KUBECONFIG=~/.kube/pr-preview.yaml kubectl delete job reaper-rotation-verify -n argocd
   ```

5. **Revoke Old Token:**
   - Once verified, return to GitHub Developer Settings and delete/revoke the retired token.

---

### 6.2 Tailscale OAuth Client (`operator-oauth` in `tailscale`)

The Tailscale Operator authenticates to the Tailscale control plane using an OAuth Client Secret to register Ingress proxies and manage tailnet devices.

#### Least-Privilege Scope Requirements:
- **Client Tags:** Must be explicitly tagged with `tag:k8s-operator`.
- **Permissions:**
  - `Devices: Read/Write` (or Core).
  - `Auth Keys: Write` (required to mint ephemeral auth keys for preview proxy pods).
- **Prohibited:** Never assign personal tags or broad network routing administrative capabilities outside `tag:k8s-operator`.

#### Step-by-Step Rotation:
1. **Generate New OAuth Client:**
   - Go to [Tailscale Admin Console](https://login.tailscale.com/admin/settings/oauth) -> Settings -> OAuth Clients.
   - Click **Generate OAuth Client**.
   - Tags: Select `tag:k8s-operator`.
   - Scopes: Check `Devices (Read/Write)` and `Auth Keys (Write)`.
   - Copy `Client ID` and `Client Secret`.

2. **Update Kubernetes Secret:**
   ```bash
   KUBECONFIG=~/.kube/pr-preview.yaml kubectl create secret generic operator-oauth \
     --namespace=tailscale \
     --from-literal=client_id="<NEW_CLIENT_ID>" \
     --from-literal=client_secret="<NEW_CLIENT_SECRET>" \
     --dry-run=client -o yaml | KUBECONFIG=~/.kube/pr-preview.yaml kubectl apply -f -
   ```

3. **Restart Operator Deployment:**
   ```bash
   KUBECONFIG=~/.kube/pr-preview.yaml kubectl rollout restart deployment operator -n tailscale
   KUBECONFIG=~/.kube/pr-preview.yaml kubectl rollout status deployment operator -n tailscale
   ```

4. **Verify Ingress & Proxy Connectivity:**
   ```bash
   # Check operator logs for successful authentication
   KUBECONFIG=~/.kube/pr-preview.yaml kubectl logs -n tailscale -l app.kubernetes.io/name=tailscale-operator --tail=40

   # Verify existing shared endpoint responds with HTTP 200
   curl -s -i https://shared.taildc1471.ts.net/healthz
   ```

5. **Revoke Old OAuth Client:**
   - In Tailscale Admin Console, delete the deprecated OAuth Client.

---

### 6.3 VirtualBox VM Host SSH Keypair (`~/.ssh/id_ed25519`)

Direct administrative access to the `devops-server` VM is restricted to key-only authentication on the private host-only adapter (`192.168.56.10:22`).

#### Step-by-Step Rotation:
1. **Generate New Ed25519 Keypair on Host:**
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_new -C "devops-server-rotation-$(date +%Y%m%d)"
   ```

2. **Append New Public Key to VM Authorized Keys:**
   ```bash
   # Copy new public key to VM authorized_keys without removing old key
   cat ~/.ssh/id_ed25519_new.pub | ssh -i ~/.ssh/id_ed25519 vboxuser@192.168.56.10 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
   ```

3. **Verify SSH Access with New Key:**
   ```bash
   ssh -i ~/.ssh/id_ed25519_new vboxuser@192.168.56.10 "echo 'New SSH key authenticated successfully'"
   ```

4. **Retire Old Key:**
   - Remove the old public key line from `~/.ssh/authorized_keys` inside the VM:
     ```bash
     ssh -i ~/.ssh/id_ed25519_new vboxuser@192.168.56.10 "sed -i '/<OLD_KEY_COMMENT>/d' ~/.ssh/authorized_keys"
     ```
   - On the host machine, backup and replace the default key:
     ```bash
     mv ~/.ssh/id_ed25519 ~/.ssh/id_ed25519_backup
     mv ~/.ssh/id_ed25519_new ~/.ssh/id_ed25519
     mv ~/.ssh/id_ed25519_new.pub ~/.ssh/id_ed25519.pub
     ```

---

### 6.4 Postgres Application Database Secret (`shared-main-app-postgres`)

Database passwords for ephemeral preview environments and the shared environment are decoupled per namespace.

#### Step-by-Step Rotation (Shared Environment):
1. **Generate New Strong Password:**
   ```bash
   NEW_PG_PASS=$(openssl rand -hex 16)
   ```

2. **Update Database User Password in PostgreSQL:**
   ```bash
   PG_POD=$(KUBECONFIG=~/.kube/pr-preview.yaml kubectl get pod -n shared -l app.kubernetes.io/component=database -o jsonpath='{.items[0].metadata.name}')
   KUBECONFIG=~/.kube/pr-preview.yaml kubectl exec -n shared "${PG_POD}" -- psql -U postgres -c "ALTER USER postgres WITH PASSWORD '${NEW_PG_PASS}';"
   ```

3. **Update Kubernetes Secret:**
   ```bash
   KUBECONFIG=~/.kube/pr-preview.yaml kubectl create secret generic shared-main-app-postgres \
     --namespace=shared \
     --from-literal=POSTGRES_USER=postgres \
     --from-literal=POSTGRES_PASSWORD="${NEW_PG_PASS}" \
     --from-literal=POSTGRES_DB=appdb \
     --dry-run=client -o yaml | KUBECONFIG=~/.kube/pr-preview.yaml kubectl apply -f -
   ```

4. **Restart App Deployment to Pick Up New Credentials:**
   ```bash
   KUBECONFIG=~/.kube/pr-preview.yaml kubectl rollout restart deployment shared-main-app -n shared
   KUBECONFIG=~/.kube/pr-preview.yaml kubectl rollout status deployment shared-main-app -n shared
   ```

5. **Verify Database Healthz:**
   ```bash
   curl -s -i https://shared.taildc1471.ts.net/readyz
   ```

---

## 7. Disaster Recovery (DR) Procedure & Drill Runbook (T-7.1)

This section provides the end-to-end Standard Operating Procedure for recovering the platform from complete cluster loss, disk failure, or VM recreation back to a 100% operational state.

### 7.1 Recovery Objectives (RTO & RPO)
- **Recovery Time Objective (RTO):** Total time to rebuild from an empty/base node to full operational state is **≤ 30 minutes** (target).
- **Recovery Point Objective (RPO):** GitOps state is completely declarative; zero state loss for application configuration, Argo CD applications, and preview definitions stored in Git. Ephemeral preview database data is ephemeral by design (non-persistent).

### 7.2 Prerequisites
1. **Host Access:** VirtualBox host machine with `ansible-playbook`, `kubectl`, `helm`, and `git`.
2. **Base Operating System:** Either a freshly installed Ubuntu Server 24.04 VM or restoring the `base vm` snapshot (`VBoxManage snapshot "devops-server" restore "base vm"`).
3. **Out-of-band Secrets:** Backed up in `~/.config/pr-preview/dr-secrets/` (`operator-oauth.yaml`, `github-token.yaml`, `shared-postgres.yaml`).

### 7.3 Step-by-Step Restoration (Automated)

The automated recovery script [`scripts/dr-restore.sh`](../scripts/dr-restore.sh) coordinates the entire rebuild and measures stopwatch duration:

```bash
# 1. Restore the VM to the clean base snapshot
VBoxManage controlvm "devops-server" poweroff
VBoxManage snapshot "devops-server" restore "base vm"
VBoxManage startvm "devops-server" --type headless

# 2. Wait 15 seconds for VM network and SSH to come online
sleep 15

# 3. Execute the automated Disaster Recovery script
bash scripts/dr-restore.sh
```

### 7.4 Step-by-Step Restoration (Manual Runbook)

If running commands interactively:

1. **Provision Node & k3s (Ansible):**
   ```bash
   ansible-playbook -i ansible/inventory/local.ini ansible/site.yml
   ```
   *Note on Kubeconfig:* Ansible automatically fetches the new `/etc/rancher/k3s/k3s.yaml` to `~/.kube/pr-preview.yaml` and updates the server IP to `192.168.56.10`.

2. **Restore Out-of-Band Secrets:**
   ```bash
   kubectl create namespace tailscale --dry-run=client -o yaml | kubectl apply -f -
   kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
   kubectl create namespace shared --dry-run=client -o yaml | kubectl apply -f -

   kubectl apply -f ~/.config/pr-preview/dr-secrets/operator-oauth.yaml
   kubectl apply -f ~/.config/pr-preview/dr-secrets/github-token.yaml
   kubectl apply -f ~/.config/pr-preview/dr-secrets/shared-postgres.yaml
   ```

3. **Bootstrap Platform Operators & Components:**
   ```bash
   bash platform/bootstrap/install-tailscale.sh
   bash platform/bootstrap/install-argocd.sh
   bash platform/bootstrap/install-monitoring.sh
   ```

4. **Deploy Platform Manifests:**
   ```bash
   kubectl apply -f platform/argocd/project-previews.yaml
   kubectl apply -f platform/argocd/application-shared.yaml
   kubectl apply -f platform/argocd/applicationset-previews.yaml
   kubectl apply -f platform/reaper/rbac.yaml
   kubectl apply -f platform/reaper/configmap.yaml
   kubectl apply -f platform/reaper/cronjob.yaml
   ```

5. **Verify System Health:**
   ```bash
   # Check pod status across platform namespaces
   kubectl get pods -A | grep -E "tailscale|argocd|monitoring|shared"

   # Verify Tier 1 Shared App responds over Tailnet
   curl -s -i https://shared.taildc1471.ts.net/healthz

   # Verify Prometheus rules loaded
   KUBECONFIG=~/.kube/pr-preview.yaml kubectl exec -n monitoring deploy/preview-exporter -- \
     python -c "import urllib.request, json; print(json.loads(urllib.request.urlopen('http://kube-prometheus-stack-prometheus.monitoring:9090/api/v1/rules').read().decode())['status'])"
   ```

### 7.5 Runbook Gaps Discovered & Resolved (T-7.1)
- **Kubeconfig Stale Authority Bug:** Previously, Ansible skipped fetching kubeconfig if `~/.kube/pr-preview.yaml` already existed on the host. During a DR drill, the new k3s installation generates a new cluster CA, causing host authentication failure (`x509: certificate signed by unknown authority`). Fixed in `ansible/roles/k3s/tasks/main.yml` to always refresh the host kubeconfig.
- **VirtualBox Base Snapshot Memory Downgrade:** Restoring the legacy `base vm` snapshot downgraded the VM to its original 2048 MB RAM instead of 8192 MB, causing severe memory exhaustion and swap thrashing during simultaneous container image pulls. Resolved by verifying and updating VM memory to 8192 MB (`VBoxManage modifyvm "devops-server" --memory 8192`).
- **Client-Side OpenAPI Discovery Cache:** When Argo CD CRDs are newly applied, the host `kubectl` cache (`~/.kube/cache/discovery`) can serve stale schema definitions causing transient `no matches for kind "ApplicationSet"` errors. Fixed in `scripts/dr-restore.sh` with automatic cache invalidation and retry logic.
- **Secret Recovery Workflow:** Documented the secure out-of-band secret directory `~/.config/pr-preview/dr-secrets/` with strict `0600` permissions outside the repository, preventing the need to re-issue external tokens during disaster events.





