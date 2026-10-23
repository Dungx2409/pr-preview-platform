# PR Preview Platform

A self-hosted DevOps platform that automatically provisions isolated, HTTPS-secured preview environments for every labeled Pull Request on a local k3s cluster.
Environments are shared privately with teammates through Tailscale and synchronized using pull-based GitOps with Argo CD.
Closing or merging a Pull Request instantly reaps all associated cluster resources, preventing resource leaks.
