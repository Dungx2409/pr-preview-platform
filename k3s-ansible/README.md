# K3s 3-Node Cluster + MetalLB L2 Automation

Playbook Ansible tự động hóa thiết lập cụm K3s (1 Master, 2 Workers) chạy trên VirtualBox Host-Only network cùng MetalLB L2 load balancer.

## Cấu trúc
```
k3s-ansible/
├── ansible.cfg
├── inventory.ini
├── site.yml             # Playbook cài đặt cụm
├── reset.yml            # Playbook dọn sạch / gỡ bỏ K3s trên cả 3 nodes
└── roles/
    ├── common/          # Cài curl, tắt swap
    ├── k3s_master/      # Cài K3s server, lấy token, fetch kubeconfig
    ├── k3s_worker/      # Join workers vào cluster với node token
    └── metallb/         # Apply MetalLB manifest & L2 IPAddressPool
```

## Cách chạy

### 1. Dọn sạch cụm cũ (nếu đã lỡ cài thủ công trước đó)
```bash
cd k3s-ansible
ansible-playbook -i inventory.ini reset.yml
```

### 2. Cài đặt toàn bộ cụm
```bash
cd k3s-ansible
ansible-playbook -i inventory.ini site.yml
```

## Kiểm tra sau khi chạy xong
```bash
# Kiểm tra nodes trong cụm
kubectl --kubeconfig ~/.kube/k3s-lab.yaml get nodes -o wide

# Kiểm tra pods của MetalLB
kubectl --kubeconfig ~/.kube/k3s-lab.yaml get pods -n metallb-system

# Kiểm tra IPAddressPool và L2Advertisement
kubectl --kubeconfig ~/.kube/k3s-lab.yaml get ipaddresspool,l2advertisement -n metallb-system
```
