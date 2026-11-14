# Review Changelog

Ghi lại mọi vấn đề phát hiện và sửa trong đợt review/dọn dẹp project.
Mỗi cụm module review xong được chốt thành 1 section + 1 git commit.

---

## Cụm 1 — Python core (demo-app, exporter, reaper)

### [demo-app/src/database.py]
| # | File:dòng | Loại | Vấn đề | Cách sửa | Mức độ |
|---|---|---|---|---|---|
| 1 | database.py:80,108,135,166 | Bug/Perf | `with _get_connection() as conn` với psycopg2 chỉ commit/rollback, **không đóng connection** → leak connection mỗi lần gọi `check_db`/`get_counter`/`increment_counter`/`init_db` | Bọc bằng `contextlib.closing()` (`with closing(...) as conn, conn:`) để vừa commit vừa close | cao |
| 2 | database.py:91 | Style | `init_db()` nuốt lỗi im lặng (`except Exception: return False`) khiến lỗi schema bị che giấu | Log `logger.warning` trước khi trả False | thấp |

### [demo-app/src/main.py]
| # | File:dòng | Loại | Vấn đề | Cách sửa | Mức độ |
|---|---|---|---|---|---|
| 3 | main.py:101,114 (cũ) | Security | `detail=f"Database unavailable: {str(e)}"` lộ chi tiết lỗi DB (host/port/tên bảng) ra client | Trả detail generic, log lỗi thật server-side | thấp |

### [exporter/src/exporter.py]
| # | File:dòng | Loại | Vấn đề | Cách sửa | Mức độ |
|---|---|---|---|---|---|
| 4 | exporter.py:360 | Bug | SIGTERM/SIGINT handler gọi `server.shutdown()` ngay trên main thread đang chạy `serve_forever()` → **deadlock khi graceful shutdown** | Gọi `server.shutdown()` trong `threading.Thread(daemon=True)` | cao |
| 5 | exporter.py:343 | Style | `if "/metrics" in args[0] if args else False` khó đọc | Viết lại `if args and "/metrics" in args[0]:` | thấp |

### [reaper/src/reaper.py]
| # | File:dòng | Loại | Vấn đề | Cách sửa | Mức độ |
|---|---|---|---|---|---|
| 6 | reaper.py:276 | Bug | Regex `ts-preview-(pr-\d+)-` bắt `pr-<N>` nhưng namespace production dùng prefix `preview-<N>` → **so khớp luôn sai, mọi proxy bị báo "stale"** | Bắt số `(\d+)`, kiểm tra cả 2 dạng `preview-<N>` và `pr-<N>` | trung |

> Ghi chú: phát hiện sơ bộ "app_name = preview-<ns_name> luôn sai" hóa ra **không đúng** — sau khi đọc ApplicationSet (`name: 'preview-{{ .namespace.prefix }}-{{ .number }}'`) thì `app_name = "preview-" + ns_name` khớp đúng naming của Argo CD. Không sửa.

---

## Cụm 2 — GitHub Actions workflows

### [.github/workflows/preview-closed.yml]
| # | File:dòng | Loại | Vấn đề | Cách sửa | Mức độ |
|---|---|---|---|---|---|
| 1 | preview-closed.yml:14 | Bug | Thiếu `contents: read` trong `permissions:` → `actions/checkout` không đọc được repo (private repo sẽ fail). Không nhất quán với 3 workflow còn lại | Thêm `contents: read` | trung |

### [.github/workflows/build.yml]
| # | File:dòng | Loại | Vấn đề | Cách sửa | Mức độ |
|---|---|---|---|---|---|
| 2 | build.yml:58,81 | Dead code + Convention | Push tag `:latest` nhưng không nơi nào pull (shared app pin sha `a55dfe6`). Vi phạm quy tắc "no latest" (AGENTS.md §11) | Bỏ tag `:latest` ở build + push | trung |

---

## Cụm 3 — Shell scripts

### [platform/bootstrap/install-argocd.sh]
| # | File:dòng | Loại | Vấn đề | Cách sửa | Mức độ |
|---|---|---|---|---|---|
| 1 | install-argocd.sh:73 | Bug/Security | Password bị nội suy thẳng vào source Python qua chuỗi shell double-quote → vỡ/inject khi password chứa `"`, `$`, `\`, backtick | Truyền password qua env var (`os.environ`) | trung |

### [scripts/test-20-cycles.sh]
| # | File:dòng | Loại | Vấn đề | Cách sửa | Mức độ |
|---|---|---|---|---|---|
| 2 | test-20-cycles.sh:76 | Convention | `tag: "latest"` — phụ thuộc mutable tag, vi phạm "no latest" | Pin `a55dfe6` (khớp shared image trong values-shared.yaml) | thấp |

### [scripts/dr-restore.sh]
| # | File:dòng | Loại | Vấn đề | Cách sửa | Mức độ |
|---|---|---|---|---|---|
| 3 | dr-restore.sh:82-89 | Bug | Vòng retry apply ApplicationSet không fail khi 6 lần đều thất bại → nuốt lỗi, DR vẫn tiếp tục | Thêm cờ `APPSET_APPLIED` + `exit 1` nếu thất bại | thấp |

---

## Cụm 4 — Helm chart (charts/app)

Không sửa code — `helm lint` pass sạch. Ghi nhận các vấn đề (xem "Cần tao quyết định").

## Cụm 5 — Platform manifests (reaper/monitoring ConfigMap)

| # | File:dòng | Loại | Vấn đề | Cách sửa | Mức độ |
|---|---|---|---|---|---|
| 1 | platform/reaper/configmap.yaml + platform/monitoring/exporter-configmap.yaml | Bug (drift) | ConfigMap **embed bản copy** của `reaper.py`/`exporter.py` — đây mới là code chạy thật, nhưng bị **lệch** khỏi `src/`: vẫn còn bug deadlock + stale-proxy (đã sửa ở cụm 1) và log sai tên app (`app_name` thay vì `target_app`) | Đồng bộ 2 ConfigMap khớp với `src/` đã sửa | cao |

## Cụm 6 — Ansible

Không sửa code — chỉ có note security thấp (xem "Cần tao quyết định").

---

## Tóm tắt

- **Bug**: 7 (2 cao: deadlock exporter, leak connection; 2 trung: stale proxy, thiếu `contents: read`; 3 thấp: retry DR nuốt lỗi, password injection, configmap log sai tên app)
- **Security**: 2 (info disclosure thấp, password injection trung)
- **Dead code / Convention**: 2 (tag `:latest` ở build.yml + test-20-cycles.sh)
- **Style**: 2 (log_message, init_db nuốt lỗi)
- **File bị ảnh hưởng nhiều nhất**: `database.py` (4 branch) + 2 ConfigMap embed Python (drift)

## Thay đổi hành vi

- `demo-app` `/counter` (GET/POST): detail 503 đổi từ `"Database unavailable: <chi tiết lỗi>"` → `"Database unavailable"` (cố ý bỏ lộ thông tin). Test không assert detail nên vẫn xanh.
- `exporter` graceful shutdown: trước đây deadlock (treo tới khi bị force-kill), giờ thoát sạch với exit 0. Đây là fix bug, không đổi API.
- `build.yml`: không còn push tag `:latest` (trước đây push nhưng không ai dùng).
- `test-20-cycles.sh`: image tag đổi từ `latest` → `a55dfe6` (pin theo shared image; hệ quả của việc bỏ `:latest`).

## Cần tao quyết định / chưa sửa

| # | File:dòng | Loại | Vấn đề | Lý do chưa sửa |
|---|---|---|---|---|
| 1 | exporter.py:118-121, reaper.py:75-78 | Security | Tự tắt TLS verify (`check_hostname=False`, `verify_mode=CERT_NONE`) khi không có CA file. In-cluster thì an toàn (có `ca.crt`), nhưng chạy ngoài cluster sẽ không verify cert → MITM | Đề xuất chuyển thành opt-in qua env (`INSECURE_SKIP_TLS_VERIFY=1`). Chưa sửa vì sợ break local dev; cần mày xác nhận |
| 2 | reaper.py:get_open_preview_prs | Bug (edge case) | `per_page=100`, không paginate. >100 open PRs sẽ bỏ sót → preview bị nhầm là orphan | Hiếm gặp với project này; nếu cần tao sẽ thêm vòng lặp theo Link header |
| 3 | exporter.py:96 | Style | `KUBERNETES_SERVICE_HOST_URL` là env var không chuẩn (dead/misleading), fallback `kubernetes.default.svc` mới đúng | Không gây hại, chỉ khó hiểu; không sửa để tránh scope creep |
| 4 | preview.yml:62,79 | Dead code | Push 2 tag (`TAG_7` và `TAG_8`) cho cùng image; `TAG_7` (`preview-<N>-<7sha>`) không được reference ở đâu | Không gây hại, chỉ thừa; chưa bỏ để tránh đổi hành vi publish |
| 5 | preview.yml:23 / preview-closed.yml:20 | Style | `TAILNET_NAME: taildc1471.ts.net` hardcode + lặp ở 2 file, chưa nằm trong `values.yaml` (single source of truth) | Không phải secret; chưa đổi để tránh scope creep |
| 6 | các workflow (actions/tools) | Verify | Version pin của actions/tools (`checkout@v7.0.1`, `setup-python@v7.1.0`, `docker/login-action@v4.6.0`, `ansible-lint==26.10.1`, `trivy-action@v0.36.0`) chưa đối chiếu official docs | CI đã chạy xanh (42 PR merged) nên tao không sửa; khuyên mày spot-check 1 lần |
| 7 | verify-teardown.sh:84 | Security smell | Dùng `eval` chạy chuỗi lệnh `kubectl ... \| jq ...` (TARGET_PR từ CLI nội suy vào jq filter) | Operator-controlled nên rủi ro thấp; refactor bỏ eval động tới ~8 call site — để dành |
| 8 | verify-access.sh / verify-security.sh | Style | Trùng lặp logic check LAN IP + Tailscale ACL giữa 2 script | Đều là script verify độc lập; tách lib chung là refactor lớn, chưa làm |
| 9 | install-argocd.sh:73 | Dependency | `bcrypt` là dependency của host, không khai trong requirements nào | Script chạy trên VM có bcrypt; nếu thiếu sẽ fail rõ ở bước rotate |
| 10 | platform/reaper/configmap.yaml + platform/monitoring/exporter-configmap.yaml | Kiến trúc | `reaper.py`/`exporter.py` tồn tại ở **2 nơi** (src/ để test + ConfigMap để chạy), không có cơ chế sync → dễ drift (đã xảy ra) | ✅ Đã xử lý: thêm `scripts/sync-configmaps.py` (sync + `--check`) + target `make check-configmaps`, wire vào `make lint` |
| 11 | platform/monitoring/values.yaml:80 | Security | Grafana `adminPassword: "admin"` hardcode | ClusterIP + localhost-only nên rủi ro thấp; khuyên đổi qua secret nếu sau này expose |
| 12 | platform/reaper/cronjob.yaml:39 | Design | `DRY_RUN: "true"` — reaper được deploy ở chế độ dry-run, **không bao giờ thực sự xoá** orphan/expired | Có thể cố ý (an toàn); nếu muốn safety-net thực sự hoạt động thì phải flip env |
| 13 | platform/reaper/cronjob.yaml + exporter-deployment.yaml | Convention | `image: python:3.10-slim` là floating tag (không pin digest) | Vi phạm "pin version"; pin digest hoặc minor nếu cần |
| 14 | exporter/reaper `load_central_config` | Dead code | Trong prod, image `python:3.10-slim` **không có PyYAML** và ConfigMap chỉ mount mỗi `.py` (không mount `values.yaml`) → `load_central_config()` luôn trả `{}`, prefix/repo bị hardcode, không theo values.yaml | Không gây lỗi hôm nay (prefix vẫn "preview"); nhưng là gap "single source of truth" |
| 15 | charts/app/values.yaml:110 | Security | `postgres.password: "preview-pg-secret"` hardcode default | Ephemeral + NetworkPolicy nên rủi ro thấp; chỉ là default |
| 16 | charts/app/values-shared.yaml:6,10 | Design | `gitSha` + `image.tag` hardcode sha `a55dfe6`; build.yml push sha mới nhưng không update file này → shared env "đóng băng" | Có thể cố ý (pin stable); nếu muốn shared theo main thì cần auto-bump |
| 17 | ansible/ansible.cfg + k3s/tasks | Security | `host_key_checking=False` + `--write-kubeconfig-mode 644` (kubeconfig world-readable) | VM dev single-user nên chấp nhận được; ghi nhận thôi |

---

## Follow-up — chốt item #10 (ConfigMap drift)

| # | File | Loại | Vấn đề | Cách sửa | Mức độ |
|---|---|---|---|---|---|
| 1 | scripts/sync-configmaps.py (mới) + Makefile | Maintainability | Không có cơ chế chống drift giữa `src/*.py` và ConfigMap embed | Thêm script `sync-configmaps.py` (sync + `--check`), target `make sync-configmaps` / `check-configmaps`, wire `check-configmaps` vào `make lint` → CI bắt drift | cao |

Sau khi chạy sync, 2 ConfigMap giờ **byte-identical** với `src/` (bỏ luôn trailing whitespace + format drift cũ).

---

## Follow-up 2 — chốt 4 mục bảo mật/platform (theo yêu cầu)

| # | File | Loại | Vấn đề | Cách sửa | Mức độ |
|---|---|---|---|---|---|
| 1 | exporter/reaper (src + ConfigMap) | Security | TLS verify tự tắt khi không có CA file → MITM risk | Chỉ tắt khi set `INSECURE_SKIP_TLS_VERIFY=1` (explicit opt-in); mặc định verify ON | trung |
| 2 | platform/reaper/cronjob.yaml | Bug/Design | Reaper chạy `DRY_RUN: "true"` → safety-net không xoá gì | Flip `DRY_RUN: "false"` để thực sự reap orphan/expired | cao |
| 3 | platform/monitoring/values.yaml + install-monitoring.sh | Security | Grafana `adminPassword: "admin"` hardcode | Bỏ hardcode → chart tự generate random password trong secret `kube-prometheus-stack-grafana` | trung |
| 4 | charts/app (values + _helpers.tpl + postgres-secret.yaml) | Security | `postgres.password: "preview-pg-secret"` dùng chung cho mọi preview | Generate password deterministic per-release (`sha256sum(release name)`), không churn, unique | thấp |
| 5 | .github/workflows/build.yml | Bug/Design | Shared env "đóng băng" — build push sha mới nhưng `values-shared.yaml` không update | Thêm bước bump `values-shared.yaml` + commit/push (cần `contents: write`) | trung |

**Thay đổi hành vi:**
- Reaper giờ **thực sự xoá** orphan/expired preview (trước chỉ log — đã flip `DRY_RUN`).
- Grafana password giờ **random** (không còn `admin/admin`); lấy từ secret `kube-prometheus-stack-grafana`.
- Shared env giờ **auto-track main** (build.yml tự bump tag `values-shared.yaml` sau mỗi push).
- TLS verify giờ **bật mặc định**; local dev phải set `INSECURE_SKIP_TLS_VERIFY=1` nếu không có CA.

Các mục tương ứng trong "Cần tao quyết định" đã giải quyết: #1 (TLS), #11 (Grafana), #12 (DRY_RUN), #15 (postgres), #16 (values-shared).

---

## Follow-up 3 — dọn code chuyên nghiệp (dead code + single source of truth)

| # | File | Loại | Vấn đề | Cách sửa | Mức độ |
|---|---|---|---|---|---|
| 1 | exporter/reaper (src + ConfigMap) | Dead code | `load_central_config()` + `_CONFIG` gây hiểu nhầm "đọc values.yaml" nhưng trong prod **luôn trả `{}`** (image slim không có PyYAML, không mount values.yaml) | Xoá hàm dead; prefix lấy từ env `PREVIEW_NAMESPACE_PREFIX`, set rõ trong manifest | trung |
| 2 | exporter/reaper | Dead code | `KUBERNETES_SERVICE_HOST_URL` là env var **không chuẩn** (không bao giờ set), fallback `kubernetes.default.svc` mới đúng | Bỏ lookup env var, dùng thẳng default | thấp |
| 3 | reaper.py | Bug | `get_open_preview_prs` không paginate → >100 open PRs bị bỏ sót → preview nhầm thành orphan | Thêm vòng lặp theo `Link` header (`_next_page_url`) | trung |
| 4 | preview.yml | Dead code | Push 2 tag (`TAG_7` + `TAG_8`) cho cùng image; `TAG_7` không ai reference (ApplicationSet dùng 8-char) | Bỏ `TAG_7` build + push | thấp |
| 5 | values.yaml + preview.yml + preview-closed.yml | Single source of truth | `TAILNET_NAME` hardcode + lặp ở workflow (preview-closed thậm chí define mà không dùng) | Đưa về `values.yaml` (`tailnet.name`), workflow đọc qua `CONFIG_TAILNET_NAME` | thấp |

Các mục "Cần tao quyết định" đã giải quyết: #2 (pagination), #3 (env var chuẩn), #4 (TAG_7), #5 (TAILNET_NAME), #14 (load_central_config dead).
