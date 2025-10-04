#!/usr/bin/env python3
"""Sync ``secondary-droplet/`` changes to the production droplet."""

import argparse
import json
import os
import pathlib
import shlex
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "deploy/deploy_config.json").read_text())

HOST = CFG["droplet_host"]
USER = CFG["ssh_user"]
KEY = os.path.expanduser(CFG["ssh_key"])


def ssh(cmd: list[str]):
    full = ["ssh", "-i", KEY, f"{USER}@{HOST}"] + cmd
    return subprocess.run(full, check=True)


def scp(local: str, remote: str):
    full = ["scp", "-i", KEY, local, f"{USER}@{HOST}:{remote}"]
    return subprocess.run(full, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    syncs = CFG["sync_map"]
    for item in syncs:
        lpath = str(ROOT / item["local"])
        rpath = item["remote"]
        mode = item.get("mode", "644")
        if_missing_only = item.get("if_missing_only", False)

        if args.dry_run:
            print("[DRY] would copy", lpath, "->", rpath, "mode", mode)
            continue

        if if_missing_only:
            rc = subprocess.run(
                [
                    "ssh",
                    "-i",
                    KEY,
                    f"{USER}@{HOST}",
                    f"test -f {shlex.quote(rpath)}",
                ],
                capture_output=True,
            )
            if rc.returncode == 0:
                print("[skip exists]", rpath)
                continue

        print("copy", lpath, "->", rpath)
        scp(lpath, rpath)
        ssh(["chmod", mode, rpath])

    # Reload systemd after potential unit updates
    if not args.dry_run:
        ssh(["systemctl", "daemon-reload"])
        ssh(["systemctl", "enable", "--now", "yt-decider-daemon.service"])
        ssh(["systemctl", "enable", "--now", "youtube-fallback.service"])
        print("Deployed and ensured services are enabled+running.")


if __name__ == "__main__":
    sys.exit(main() or 0)
