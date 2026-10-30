#!/usr/bin/env python3
"""Synchronize ConfigMap-embedded Python scripts with their src/ source.

The exporter and reaper run from Python files embedded as ConfigMap data
(platform/reaper/configmap.yaml, platform/monitoring/exporter-configmap.yaml),
but their canonical, tested source lives in src/. Those two copies drift
unless kept in sync — bug fixes made in src/ never reach the running cluster.

Mirrors scripts/sync-config.py (values.yaml -> platform manifests).

Usage:
  scripts/sync-configmaps.py          # write src/ contents into the ConfigMaps
  scripts/sync-configmaps.py --check  # exit 1 if any ConfigMap is out of sync
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

# (source file, configmap file, configmap data key)
MAPPINGS = (
    ("reaper/src/reaper.py", "platform/reaper/configmap.yaml", "reaper.py"),
    (
        "exporter/src/exporter.py",
        "platform/monitoring/exporter-configmap.yaml",
        "exporter.py",
    ),
)


def embed_script(document: str, key: str, content: str) -> str:
    """Replace the block scalar for `key` in a ConfigMap document.

    The ConfigMap stores the script as ``key: |`` followed by the source
    indented by 4 spaces. Everything after that marker is regenerated.
    """
    marker = f"  {key}: |\n"
    idx = document.index(marker)
    head = document[: idx + len(marker)]
    # Indent each non-empty line by 4 spaces; empty lines stay empty.
    body = "\n".join(("    " + line) if line else "" for line in content.splitlines())
    return head + body + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync ConfigMap-embedded scripts with src/")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether ConfigMaps are in sync without writing",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    out_of_sync = False

    for src_rel, cm_rel, key in MAPPINGS:
        src_path = repo_root / src_rel
        cm_path = repo_root / cm_rel

        if not src_path.exists() or not cm_path.exists():
            print(f"WARNING: {src_rel} or {cm_rel} not found; skipping.", file=sys.stderr)
            continue

        src = src_path.read_text(encoding="utf-8")
        document = cm_path.read_text(encoding="utf-8")
        config = yaml.safe_load(document) or {}
        embedded = config.get("data", {}).get(key)

        if embedded is None:
            print(f"ERROR: data.{key} missing in {cm_rel}.", file=sys.stderr)
            return 1

        if embedded != src:
            out_of_sync = True
            if args.check:
                print(f"OUT OF SYNC: {cm_rel} != {src_rel}", file=sys.stderr)
            else:
                try:
                    new_document = embed_script(document, key, src)
                except ValueError:
                    print(
                        f"ERROR: could not find marker '  {key}: |' in {cm_rel}.",
                        file=sys.stderr,
                    )
                    return 1
                cm_path.write_text(new_document, encoding="utf-8")
                print(f"✓ Updated {cm_rel} from {src_rel}")

    if args.check:
        if out_of_sync:
            print(
                "ERROR: ConfigMap-embedded scripts out of sync with src/. "
                "Run 'make sync-configmaps'.",
                file=sys.stderr,
            )
            return 1
        print("✓ All ConfigMap-embedded scripts are synchronized with src/.")
        return 0

    if not out_of_sync:
        print("✓ All ConfigMap-embedded scripts already in sync with src/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
