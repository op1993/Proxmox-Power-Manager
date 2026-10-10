#!/usr/bin/env python3
"""Conservative LXC removal observer.

A missing CT config is not sufficient evidence of deletion. This watcher
requires healthy pmxcfs and three observations before flagging cleanup.
No services, containers, credentials or user data are deleted here.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

MANIFEST = Path('/etc/proxmox-power-manager/installation.json')
RECOVERY = Path('/var/lib/proxmox-power-manager/state.json')
COUNTER = Path('/var/lib/proxmox-power-manager/missing-count')
READY = Path('/var/lib/proxmox-power-manager/cleanup-ready')
MEMBERS = Path('/etc/pve/.members')


def cluster_healthy():
    try:
        members = json.loads(MEMBERS.read_text())
        if not members.get('cluster', {}).get('quorate', False):
            return False
        result = subprocess.run(['pvesh', 'get', '/cluster/status', '--output-format', 'json'],
                                capture_output=True, text=True, timeout=15, check=True)
        return isinstance(json.loads(result.stdout), list)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def inspect():
    if not MANIFEST.is_file():
        return 'unregistered'
    data = json.loads(MANIFEST.read_text())
    ctid = data.get('web_ctid')
    if data.get('schema') != 1 or type(ctid) is not int or not 100 <= ctid <= 999999:
        return 'invalid-manifest'
    if data.get('web_ct_created_by_ppm') is not True:
        return 'external-container'
    if RECOVERY.exists():
        return 'recovery-pending'
    if not cluster_healthy():
        return 'cluster-unavailable'
    if Path(f'/etc/pve/lxc/{ctid}.conf').is_file():
        COUNTER.unlink(missing_ok=True)
        READY.unlink(missing_ok=True)
        return 'present'
    # Only mark a possible deletion. A separate explicit cleanup step is needed.
    COUNTER.parent.mkdir(parents=True, exist_ok=True)
    count = int(COUNTER.read_text()) + 1 if COUNTER.is_file() else 1
    COUNTER.write_text(str(min(count, 3)) + '\n')
    if count >= 3:
        READY.write_text(str(ctid) + '\n')
        return 'cleanup-ready'
    return 'missing-unconfirmed'


if __name__ == '__main__':
    try:
        print(inspect())
    except (OSError, ValueError, KeyError) as exc:
        print(f'unknown: {exc}', file=sys.stderr)
        sys.exit(1)
