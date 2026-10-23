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

