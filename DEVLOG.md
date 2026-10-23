# DEVLOG.md

> The project's memory. Agents read the **Decisions**, **Gotchas**, and last 2–3 **Session entries** at the start of each session, and append a new entry after each task (AGENTS.md §8).
> Rules: newest session entry on top · only measured numbers in Metrics · never paste secrets · keep entries short.

---

## Decisions (ADR-lite — append only; to change one, add a new row that supersedes it)

| ID | Date | Decision | Why | Status |
|---|---|---|---|---|
| D-001 | 2026-10-21 | Build **PR Preview Environments** as the personal CV project (instead of the earlier Deployment Hub idea) | Better DevOps signal (IaC, K8s, GitOps, TLS, security) + real pain point + demoable | Accepted |
| D-002 | 2026-10-21 | Host on **GCP** (single `e2-standard-2` VM, `asia-southeast1`) | Owner has Google AI Pro credits (monthly Cloud credit) and possibly the new-customer trial; Singapore region is close | Accepted |
| D-003 | 2026-10-21 | **k3s single node**, Terraform (cloud) + Ansible (node) | Light, reproducible, shows both IaC skills | Accepted |
| D-004 | 2026-10-21 | **Pull-based GitOps** with Argo CD ApplicationSet (PR generator), gated by label `preview`; CI holds no cluster credentials | Security + GitOps story; label doubles as fork-safety gate | Accepted |
| D-005 | 2026-10-21 | **One wildcard cert** (DNS-01 via Cloudflare) as Traefik default TLS store | Avoid Let's Encrypt rate limits from per-PR certs | ~~Accepted~~ **Superseded/Fallback** — replaced by D-013 (Tailscale Operator) if spike passes; falls back to D-013 fallback path (sslip.io / Traefik inside tailnet) if not. See SPEC v2.0 §4.1. |
| D-006 | 2026-10-21 | Push-based deploy is only an **optional spike** (T-4.7) for a write-up, not the main path | Avoid building the lifecycle twice; keep scope small | Accepted |
| D-007 | 2026-10-21 | Demo app = **Python/FastAPI + ephemeral Postgres**; secrets created out-of-band | Small, readable; scope control | Accepted (changeable) |
| D-008 | 2026-10-21 | Design stays **cloud-portable** (everything inside k3s; only Terraform is GCP-specific) | AWS or another VPS remains possible | Accepted |
| D-009 | 2026-10-21 | **IP-mode / sslip.io fallback:** dùng sslip.io hostname + Traefik + Let's Encrypt HTTP-01 (không cần domain riêng) nếu DNS-01 không khả thi | Giải pháp nhanh khi chưa có domain; không phụ thuộc Cloudflare | ~~Accepted~~ **Superseded/Fallback** — thay thế bởi D-013 (Tailscale Operator); giữ lại làm fallback nếu T-2.0 NO-GO (bên trong tailnet/LAN) |
| D-010 | 2026-10-23 | **Local-first development:** phát triển trên VM VirtualBox (Ubuntu Server, NAT + host-only network) chạy trên máy Linux cá nhân của chủ dự án (Intel gen 11, 24 GB RAM). GCP/Terraform chuyển thành tùy chọn ở Phase 8 (cloud variant) và không còn là yêu cầu bắt buộc để phát triển chính. | Không tốn credit GCP trong khi phát triển; vòng lặp thử nghiệm nhanh hơn; 24 GB RAM đủ cho k3s + toàn bộ stack. | Accepted |
| D-011 | 2026-10-23 | **Đề xuất — Tailscale Funnel spike:** dùng Tailscale Kubernetes Operator + Funnel để mỗi PR có URL HTTPS công khai dạng `pr-<N>.<tailnet>.ts.net`, thay thế sslip.io + Traefik TLS + cert-manager nếu spike đạt yêu cầu. | Funnel cấp TLS tự động và URL công khai mà không cần domain riêng hay Let's Encrypt rate-limit workaround; operator chạy trong cluster, giữ nguyên mô hình pull-based. | **Proposed — chờ kết quả spike T-2.0** |
| D-012 | 2026-10-23 | **Chuyển sang SPEC v2.0:** local-first (VirtualBox VM), chia sẻ preview **riêng tư** qua Tailscale tailnet, **2 tier** (Tier 1 shared + Tier 2 per-PR). GCP/domain/Funnel là tùy chọn ở Phase 8. Supersedes toàn bộ nội dung v1 liên quan đến GCP bắt buộc, domain, và public TLS. | Không cần cloud account hay domain để bắt đầu; 24 GB RAM đủ; private-by-default phù hợp với nhóm nhỏ; hai tier thể hiện cả shared-staging lẫn per-PR isolation. | Accepted |
| D-013 | 2026-10-23 | **Tailscale Kubernetes Operator** (Ingress `ingressClassName: tailscale`, **không dùng Funnel**) để mỗi preview có URL `https://<name>.<tailnet>.ts.net` với TLS hợp lệ, chỉ truy cập được bởi thành viên tailnet. Fallback nếu NO-GO: `tailscale serve` trên VM + sslip.io/Traefik bên trong tailnet/LAN. | Không cần domain riêng; TLS tự động; private mặc định; operator chạy trong cluster, giữ pull-based. | **Proposed — chờ kết quả spike T-2.0** |

## Metrics (measured only — fill when you actually measure)

| Metric | Target | Result | Date | How measured |
|---|---|---|---|---|
| PR labeled → URL healthy (p50 / p95) | p50 ≤ 5 min | — | — | — |
| PR closed → everything gone | ≤ 3 min | — | — | — |
| Rebuild from empty project | ≤ 30 min | — | — | — |
| Leaks after 20 open/close cycles | 0 | — | — | — |
| Node RAM headroom with full stack | ≥ 20 % free | — | — | — |
| Monthly credit burn (VM running N h/mo) | within budget | — | — | — |
| Tạo Ingress Tailscale → URL truy cập được lần đầu | ≤ 60 s | — | — | — |
| RAM operator + proxy pod mỗi preview | ≤ TBD | — | — | — |
| PR labeled → link truy cập được (p50 / p95) | p50 ≤ 5 min | — | — | timestamps + exporter |
| RAM operator + mỗi proxy pod (1 / 3 / 5 Ingresses) | ≤ TBD (đo T-2.0) | — | — | `kubectl top pod` trong spike |
| Tagged resources đang dùng (Tailscale free plan cap = 50) | < 50 | — | — | Tailscale admin console |
| Phút ephemeral đã dùng/tháng (free plan cap = 1 000 min) | < 1 000 | — | — | Tailscale admin console |
| Số preview đồng thời tối đa trên VM (fit RAM/CPU) | ≥ 5 | — | — | load test + `kubectl top node` |

## Gotchas (lasting lessons — symptom → cause → fix)

_(empty — add as discovered. Pre-known traps are listed in AGENTS.md §13.)_

## Open questions / blockers

| # | Question | Owner | Status |
|---|---|---|---|
| Q-1 | Which domain on Cloudflare? (needed before T-1.4 / T-2.x) | 👤 | **Closed** — không cần domain trong v2.0 (local-first + Tailscale). Domain vẫn là tùy chọn Phase 8. |
| Q-2 | Has the GCP new-customer trial been used before? (affects credit budget) | 👤 | **Closed** — GCP không cần trong v2.0; chuyển sang Phase 8 optional. |
| Q-3 | VM size after measuring RAM (start `e2-standard-2`) | 🤖/👤 | Open — đo sau khi stack chạy đủ (T-1.6 + T-2.1) |
| Q-4 | Cơ chế "preview đã lên chưa" — phương án A (poll URL từ CI), B (wait-for Deployment), hay C (exporter webhook)? | 🤖/👤 | Open — nghiên cứu và đề xuất trong T-2.0 |
| Q-5 | Repo nhóm: **public** hay **private**? (ảnh hưởng `imagePullSecret`, GHCR visibility, fork-safety scope) | 👤 | Open — chủ dự án quyết định trước T-7.5 |
| Q-6 | Giới hạn user của gói Tailscale Personal free (hiện tại ~6 users theo tài liệu; xác nhận trên trang pricing chính thức) | 🤖 | Open — xác nhận trong T-0.1 / T-2.0 |
| Q-7 | Khi nào dời cluster lên máy 24/7 (server riêng hay cloud)? Điều kiện kích hoạt? | 👤 | Open — để lại đến sau Phase 7 demo |

## Ideas parking lot (not scheduled)

- Cosign signing + admission policy · Loki logs · scale-to-zero · Slack/Discord notifications · basic-auth on previews · Sealed Secrets/SOPS

---

## Session log (newest first)

### Template — copy for each task

```
### YYYY-MM-DD — T-x.y — <short title>
**Did:** what changed (files, key commands)
**Why this approach:** 1–3 lines (alternatives considered)
**Verified:** commands + result (summarized)
**Gotchas / decisions:** anything new (also copy lasting items into the sections above)
**Learned (interview note):** 2–4 lines, plain English, "I can explain this because…"
**Next:** proposed next task + any 👤 steps needed
```

### 2026-10-23 — T-0.1 — GitHub Repository setup & Phase 0 completion
**Did:** Initialized standalone git repository directly in `Documents/pr-preview-platform`. Created public GitHub repository `Dungx2409/pr-preview-platform` via GitHub CLI. Configured GitHub label `preview`. Configured branch protection rules on `main` (enforced strict PR check on "Lint & Safety Checks", disallowing force pushes and branch deletions). Resolved upstream Ansible collection requirement on CI runner. Verified base CI workflow execution (`✓ passed`).
**Why this approach:** Hosting the git root at the repository root guarantees that GitHub Actions workflows trigger correctly from `.github/workflows/` and establishes the required PR gate before Phase 1.
**Verified:** `gh repo view Dungx2409/pr-preview-platform` confirmed public status; `gh run list` confirmed green CI run on commit `7f6b1cd`; `gh api .../branches/main/protection` confirmed protection rules active.
**Gotchas / decisions:** GitHub Actions runner requires `ansible-galaxy collection install -r ansible/requirements.yml` to resolve `community.general` and `ansible.posix` modules during `ansible-lint`.
**Learned (interview note):** Branch protection rules enforce code quality and security checks before any code reaches production branches, ensuring GitOps repositories maintain deterministic and verified states.
**Next:** Phase 0 complete. Proceed to Phase 1: T-1.0 (Local VM documentation & snapshot) and T-1.5 (Ansible role common).

### 2026-10-23 — T-0.4 — Makefile + pre-commit + base CI
**Did:** Created `Makefile` with targets `lint` (`yamllint`, `ansible-lint`, `shellcheck`, `gitleaks`), `test`, `tf-plan`, `ansible-check`, `helm-template`, `verify-teardown`. Created `.yamllint.yaml` and `.ansible-lint` configurations. Fixed formatting issues across all Ansible playbooks/roles. Created `.pre-commit-config.yaml` with pinned gitleaks, yamllint, and shellcheck hooks. Created `.github/workflows/ci.yml` running `make lint` and `make test` using pinned actions (`actions/checkout@v7.0.1`, `actions/setup-python@v7.1.0`). Verified secret detection with a throw-away branch test.
**Why this approach:** Provides a unified command interface via `make` across local developer environments and CI, ensuring identical linting and validation behavior.
**Verified:** `make lint` passed with 0 errors/warnings across all linters. Created throw-away branch `test/fake-secret-check` with a synthetic fake secret token; verified `gitleaks` caught it with exit code 1; removed the test branch and confirmed clean git history.
**Gotchas / decisions:** Set `comments-indentation: false` in `.yamllint.yaml` to ensure compatibility with `ansible-lint`'s YAML formatting rules.
**Learned (interview note):** Standardizing local checks (`make lint`, pre-commit) to match remote CI checks prevents "works on my machine" issues and catches syntax/secret issues before code is pushed to remote repositories.
**Next:** Phase 0 complete. Await human confirmation for T-0.1 checklist before proceeding to Phase 1 (T-1.0 / T-1.5).

### 2026-10-23 — T-0.3 — Pin versions
**Did:** Researched official stable releases from upstream endpoints and recorded pinned versions into `docs/versions.md` for all components listed in SPEC v2.0 §4.2: k3s (`v1.36.5+k3s1`), Argo CD (`v3.5.6`), Tailscale Operator Helm chart (`1.104.2`), kube-prometheus-stack Helm chart (`92.11.0` / appVersion `v0.94.1`), Ansible core (`2.16.19`), Python base image (`python:3.10-slim`), Postgres image (`postgres:16-alpine`), Trivy (`v0.76.1`), GitHub Actions (`actions/checkout@v7.0.1`, `actions/setup-python@v7.1.0`, `docker/login-action@v4.6.0`, `docker/build-push-action@v7.4.0`, `aquasecurity/trivy-action@v0.36.0`), VirtualBox (`7.2.10r174163`), Ubuntu Server LTS (`24.04 LTS`).
**Why this approach:** Explicit version pinning avoids unexpected upstream breaks, guarantees deterministic CI runs, and aligns with AGENTS.md §4 ("no latest tags").
**Verified:** Queried upstream release endpoints and local CLI tools (k3s release channels API, GitHub releases API, Tailscale Helm index, Prometheus Community Helm index, Docker Hub API, `VBoxManage --version`, `lsb_release`).
**Gotchas / decisions:** k3s stable is currently `v1.36.5+k3s1`. Host client kubectl is `v1.35.9`, which is within the Kubernetes 1-minor-version skew policy.
**Learned (interview note):** In production Kubernetes and GitOps pipelines, floating tags like `:latest` or unpinned Helm chart versions introduce non-deterministic state drifting; pinning all artifacts to specific release SHAs/versions guarantees reproducibility.
**Next:** T-0.4 — Implement Makefile, pre-commit hooks, and base CI workflow.

### 2026-10-23 — T-0.2 — Repo skeleton
**Did:** Created the repository layout from SPEC §5 (`platform/{bootstrap,argocd,tailscale,monitoring,reaper}`, `charts/app`, `demo-app`, `exporter`, `scripts`, `.github/workflows`, `docs`, `infra/terraform`). Added `infra/terraform/README.md` explaining Phase 8 deferral. Created comprehensive `.gitignore` blocking kubeconfig, keys/certs, env files, venv, tfstate, and local inventory. Created `README.md` with a 3-line project summary. Created `.editorconfig`, `CODEOWNERS`, `.github/PULL_REQUEST_TEMPLATE.md`. Moved local inventory to `ansible/inventory/local.ini` (git-ignored) and created `ansible/inventory/local.ini.example`.
**Why this approach:** Implements defensive repository practices from day zero. Ensures secrets and environment-specific configs cannot be accidentally tracked. Placeholders maintain repository structure for GitOps and CI tooling.
**Verified:** `find . -maxdepth 3` matched SPEC §5; tested `.gitignore` with synthetic sensitive files (`test.kubeconfig`, `test.pem`, `.env`, `.venv_test`, `test.tfstate`, `test.tfvars`, `ansible/inventory/local.ini`) — all successfully ignored.
**Gotchas / decisions:** Ensured `*venv*` pattern handles both file and directory virtual environment variations. Git root is currently at `$HOME`, so files must be explicitly staged within the repository path.
**Learned (interview note):** A robust `.gitignore` and explicit inventory templates (`local.ini.example`) prevent credential leaks before any automation or CI pipeline is introduced, fulfilling the shift-left security principle.
**Next:** T-0.3 — Pin versions for all dependencies in `docs/versions.md`.

### 2026-10-23 — T-0.2 — IN PROGRESS / recovered state
**Did:** Tiếp quản phiên làm việc bị ngắt do hết quota. Kiểm tra toàn bộ hệ thống bằng read-only checks: 12/12 công cụ (git, VBoxManage, ansible, ansible-lint, kubectl, helm, docker, make, python3, yamllint, shellcheck, gitleaks) đã sẵn sàng trong `~/.local/bin`; kubeconfig được tách an toàn ra `~/.kube/pr-preview.yaml` (chmod 600) và xoá khỏi repo; VM `devops-server` đã có snapshot `k3s-ok` (đang tắt); commit WIP `947518a` cho các tài liệu v2.0 và ansible configs hiện có.
**Why this approach:** Tuân thủ quy trình handoff khẩn cấp để bảo lưu trạng thái dở dang, đảm bảo không có secret nào bị lọt vào Git trước khi triển khai các kiểm soát an toàn (.gitignore) của T-0.2.
**Verified:** `which <12 tools>` đầy đủ; `ls -la ~/.kube/pr-preview.yaml` quyền 600; `VBoxManage showvminfo "devops-server"` trả về 8GB RAM / 2 vCPU / NAT+hostonly; `git commit` WIP sạch secrets.
**Gotchas / decisions:** Phát hiện Git repo gốc đang nằm ở `/home/dungluong/.git` (bao trùm cả home directory). Cần cẩn trọng tuyệt đối khi dùng `git add` đích danh và bắt buộc phải có `.gitignore` bao quát để ngăn rò rỉ file cá nhân.
**Learned (interview note):** Khi tiếp quản hệ thống sau sự cố gián đoạn (abrupt termination), nguyên tắc hàng đầu là Read-Only audit: kiểm tra tính toàn vẹn của file, trạng thái tài nguyên thực tế (VM/cluster), cô lập credential ra ngoài repo trước khi tạo bất kỳ thay đổi nào mới.
**Next:** 
1. Tạo `.gitignore` chuẩn bảo vệ secret và file hệ thống.
2. Hoàn thiện skeleton theo SPEC §5 (README stub, .editorconfig, CODEOWNERS, PR template, các thư mục placeholder).
3. Chuẩn hoá `ansible/inventory/` (tạo `local.ini.example` và git-ignore `local.ini`).

### 2026-10-23 — Decision — SPEC v2.0 + TASK rewrite
**Did:** SPEC.md được viết lại thành v2.0 (local-first VirtualBox, private tailnet, 2 tier); TASK.md được rewrite để khớp (T-1.1–T-1.4 bỏ, T-1.0 mới, T-2.0 spike mới, T-3.5 Tier 1, T-7.5 onboarding, Phase 8 GCP optional). DEVLOG cập nhật: D-005 và D-009 → Superseded/Fallback; D-012 (SPEC v2.0) Accepted; D-013 (Tailscale Operator) Proposed. Q-1 và Q-2 đóng; Q-4–Q-7 mở. Metrics mở rộng với 5 dòng mới. Không có code hay cloud resource nào thay đổi.
**Why this approach:** v1 đòi GCP + domain + Cloudflare — những thứ chưa có và gây tốn credit. v2 chạy hoàn toàn local (VirtualBox + Tailscale), miễn phí và vòng lặp thử nghiệm nhanh hơn. Hai tier (shared + per-PR) thể hiện thêm kỹ năng (không chỉ per-PR). Private-by-default thích hợp cho nhóm nhỏ và phù hợp với free plan Tailscale.
**Verified:** Chỉ sửa tài liệu; không có lệnh hạ tầng nào được chạy.
**Gotchas / decisions:** D-012 Accepted. D-013 Proposed — phụ thuộc kết quả T-2.0. Cần xác nhận giới hạn user Tailscale free plan trên trang pricing chính thức (Q-6). Ephemeral minutes cap (1 000/tháng) có thể là NO-GO nếu proxy pod bị coi là ephemeral resource (cần đo trong T-2.0).
**Learned (interview note):** Tailscale Operator dùng mô hình "một proxy pod per Ingress" — mỗi preview có node riêng trong tailnet, dễ revoke và audit. Khác với một VPN gateway chung: ít blast radius hơn nếu một preview bị xâm phạm. Trade-off: dùng quota tagged resources và ephemeral minutes của free plan.
**Next:** T-0.1 (👤 prerequisites theo SPEC v2.0 — GitHub public repo, VirtualBox VM, Tailscale free account); sau đó T-0.2.

### 2026-10-23 — Decision — local-first + Tailscale
**Did:** Thêm D-010 (local-first VirtualBox) và D-011 (Tailscale Funnel spike) vào Decisions. Cập nhật `SPEC.md` (D14, D15, §4.3) và `TASK.md` (T-1.1–T-1.4 deferred, T-1.6 local acceptance, T-2.0 rewritten, Phase 8 added). Không có code hay cloud resource nào bị thay đổi.
**Why this approach:** Phát triển local trước giúp tiết kiệm credit GCP và tăng tốc vòng lặp thử nghiệm. Tailscale Funnel là lựa chọn thay thế cho cert-manager + Cloudflare DNS mà không cần domain riêng — nhưng cần spike để xác nhận.
**Verified:** Chỉ sửa tài liệu; không có lệnh hạ tầng nào được chạy.
**Gotchas / decisions:** D-010 Accepted. D-011 Proposed — phụ thuộc kết quả T-2.0. Funnel chỉ hỗ trợ cổng 443/8443/10000, tên miền `*.ts.net`, và yêu cầu Tailscale auth key quản lý riêng — xem SPEC §4.3 để biết giới hạn đầy đủ.
**Learned (interview note):** Tailscale Funnel là tính năng cho phép node trong tailnet expose dịch vụ ra internet công khai qua proxy của Tailscale, với TLS tự động. Khác với Tailscale VPN (chỉ private), Funnel tạo URL công khai mà không cần cấu hình DNS hay cert riêng.
**Next:** T-2.0 — Tailscale Funnel spike (go/no-go); chủ dự án quyết định sau khi có kết quả.

### 2026-10-21 — Kickoff — planning and docs
**Did:** Defined the project and wrote `SPEC.md`, `AGENTS.md`, `TASK.md`, `DEVLOG.md`. No code or cloud resources yet.
**Why this approach:** Compared several CV-project ideas; chose PR Preview Environments because it covers IaC, K8s, GitOps, TLS automation, security, and observability with a visible demo. Free-tier research: AWS free plan is credit-based and closes the account after 6 months, so GCP (AI Pro credits + possible trial) chosen; design kept cloud-portable.
**Verified:** n/a (documentation only).
**Gotchas / decisions:** see D-001 … D-008; open questions Q-1 … Q-3.
**Learned (interview note):** Pull-based GitOps means the cluster fetches desired state from Git, so CI never needs cluster credentials, which shrinks the attack surface compared with push-based deploys.
**Next:** T-0.1 (👤 prerequisites), then T-0.2 repo skeleton.
