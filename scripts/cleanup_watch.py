#!/usr/bin/env python3
"""Conservative LXC removal observer.

A missing CT config is not sufficient evidence of deletion. This watcher
requires healthy pmxcfs and three observations before flagging cleanup.
No services, containers, credentials or user data are deleted here.
"""
import json
from pathlib import Path
import subprocess
import sys

MANIFEST = Path('/etc/proxmox-power-manager/installation.json')
RECOVERY = Path('/var/lib/proxmox-power-manager/state.json')
COUNTER = Path('/var/lib/proxmox-power-manager/missing-count')
READY = Path('/var/lib/proxmox-power-manager/cleanup-ready')
MEMBERS = Path('/etc/pve/.members')
LXC_CONFIG_DIR = Path('/etc/pve/lxc')


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


def container_registered_in_cluster(ctid):
    """Fail closed when cluster inventory cannot be queried."""
    result = subprocess.run(
        ['pvesh', 'get', '/cluster/resources', '--type', 'vm',
         '--output-format', 'json'],
        capture_output=True, text=True, timeout=15, check=True,
    )
    resources = json.loads(result.stdout)
    if not isinstance(resources, list):
        raise ValueError('Invalid cluster resource response')
    return any(
        item.get('type') == 'lxc' and str(item.get('vmid')) == str(ctid)
        for item in resources if isinstance(item, dict)
    )


def reset_confirmation():
    COUNTER.unlink(missing_ok=True)
    READY.unlink(missing_ok=True)


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
        reset_confirmation()
        return 'recovery-pending'
    if not cluster_healthy():
        reset_confirmation()
        return 'cluster-unavailable'
    if (LXC_CONFIG_DIR / f'{ctid}.conf').is_file():
        reset_confirmation()
        return 'present'
    # A container moved to another node must never be treated as deleted.
    try:
        if container_registered_in_cluster(ctid):
            reset_confirmation()
            return 'present-on-another-node'
    except (OSError, ValueError, subprocess.SubprocessError):
        reset_confirmation()
        return 'cluster-inventory-unavailable'
    # Only mark a possible deletion. A separate explicit cleanup step is needed.
    COUNTER.parent.mkdir(parents=True, exist_ok=True)
    try:
        count = int(COUNTER.read_text().strip()) + 1 if COUNTER.is_file() else 1
    except ValueError:
        count = 1
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
