# Platform Demo Assets & Visual Guide

> A checklist and operational guide for capturing real demonstration assets (screen recordings, animated GIFs, and system dashboard screenshots) for the **PR Preview Platform** portfolio per TASK T-7.3.

---

## 1. Why Visual Assets Matter

Recruiters, hiring managers, and interviewers typically spend **under 60 seconds** evaluating a GitHub portfolio project. High-quality visual assets provide immediate, undeniable proof that:
1. The platform actually runs end-to-end (not just theoretical code).
2. The user experience is polished and automated (PR label → bot comment → private HTTPS URL).
3. The observability stack (Prometheus & Grafana) actively tracks production metrics.

All screenshots and GIFs referenced in [`README.md`](../../README.md) are stored in this directory (`docs/img/`).

---

## 2. Target Assets Checklist

| Filename | Type | Purpose | Target Dimensions |
|---|---|---|---|
| [`preview-lifecycle.gif`](preview-lifecycle.gif) | Animated GIF / Video | End-to-end demo: open PR → bot comment → live preview → teardown | 1280x720 or 1440x900 (≤ 10 MB) |
| [`grafana-dashboard.png`](grafana-dashboard.png) | High-Res PNG | Grafana dashboard showing active previews, TTR, and RAM headroom | 1920x1080 or 1440x900 |
| [`argocd-previews.png`](argocd-previews.png) | High-Res PNG | Argo CD UI showing ApplicationSet and healthy preview applications | 1920x1080 or 1440x900 |
| [`tailscale-admin.png`](tailscale-admin.png) | High-Res PNG | Tailscale admin console showing active mesh proxy nodes with `tag:k8s` | 1920x1080 or 1440x900 |

---

## 3. Detailed Asset Specifications & Capture Steps

### Asset 1: `preview-lifecycle.gif` (End-to-End Walkthrough)
**Storyline (45–60 seconds):**
1. **Trigger:** Open a pull request on GitHub (or add label `preview` to an existing PR).
2. **CI Pipeline:** Show GitHub Actions workflow `Preview Build & Push` completing in ~1.5 minutes (can be sped up 2x–4x in video editor).
3. **Bot Comment:** Show the bot automatically posting the markdown comment containing the private preview URL:
   `https://preview-<N>.taildc1471.ts.net`.
4. **Live Verification:** Click the link in a browser (connected to Tailnet):
   - Show browser lock icon (valid Let's Encrypt TLS certificate).
   - Show FastAPI JSON payload (`status: ok`, database counter incrementing on reload).
5. **Teardown:** Close or merge the pull request. Show:
   - PR comment updated to closed status.
   - Namespace and Tailscale proxy pod automatically deleted in Kubernetes with zero leftover resources.

### Asset 2: `grafana-dashboard.png` (Platform Observability)
**Capture Steps:**
1. Port-forward Grafana to localhost:
   ```bash
   kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80
   ```
2. Open browser to `http://localhost:3000` (credentials in runbook).
3. Open dashboard **"PR Preview Platform - Metrics & Health"**.
4. Ensure at least one preview is active so panels display live data:
   - **Active Previews:** Gauge showing count ≥ 1.
   - **Time-to-Ready:** Gauge showing median ~102s.
   - **RAM Headroom:** Gauge showing ~51.3% free headroom.
   - **Resource Usage per Namespace:** Stacked graphs showing app + Postgres + proxy pod footprints (~16.5 MiB).
5. Press `F11` (Full screen) and capture clean browser view without bookmarks bar.

### Asset 3: `argocd-previews.png` (GitOps Engine)
**Capture Steps:**
1. Port-forward Argo CD to localhost:
   ```bash
   kubectl port-forward -n argocd svc/argocd-server 8080:443
   ```
2. Open browser to `https://localhost:8080` (credentials: `admin` / rotated password).
3. Open the **Applications** view.
4. Show the `previews` ApplicationSet card alongside active `preview-preview-<N>` and `shared-main` applications with green **Synced** and **Healthy** badges.
5. Click into one preview Application to display the live Kubernetes resource tree (Namespace, ServiceAccount, ResourceQuota, NetworkPolicy, Deployment, Service, Ingress).

### Asset 4: `tailscale-admin.png` (Zero-Trust Mesh & MagicDNS)
**Capture Steps:**
1. Open `https://login.tailscale.com/admin/machines`.
2. Filter by tag: `tag:k8s`.
3. Show the provisioned proxy pods with green connected status, assigned Tailscale IPv4 addresses (`100.x.y.z`), and valid HTTPS TLS certificates.
4. Blur or redact any personal email addresses or sensitive machine IDs before committing.

---

## 4. Recommended Tools & Optimization on Linux

### Recommended Screen Recorders:
- **Kooha:** Clean, modern screen recorder supporting native GIF or WebM/MP4 export:
  ```bash
  sudo apt install kooha
  ```
- **OBS Studio:** Professional screen recorder for 60fps high-bitrate captures:
  ```bash
  sudo apt install obs-studio
  ```
- **Peek:** Lightweight animated GIF recorder for small window captures:
  ```bash
  sudo apt install peek
  ```

### High-Quality GIF Conversion with FFmpeg:
If recording as `.mp4` or `.mkv`, generate a high-quality palette-optimized GIF to keep file size under 10 MB:

```bash
ffmpeg -i recording.mp4 -filter_complex \
  "[0:v] fps=15,scale=1280:-1:flags=lanczos,split [a][b];[a] palettegen=max_colors=128 [p];[b][p] paletteuse=dither=bayer" \
  docs/img/preview-lifecycle.gif
```

### High-Resolution Screenshots via Chrome DevTools:
1. Open the target web page in Google Chrome.
2. Press `F12` to open DevTools.
3. Press `Ctrl + Shift + P` (Command Menu).
4. Type `Capture screenshot` or `Capture full size screenshot` and press Enter.
5. Save the resulting image as PNG directly to `docs/img/`.
