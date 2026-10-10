#!/usr/bin/env python3
"""Observe a Power Manager LXC without performing destructive actions.

The installer may register an owned container in installation.json.
This observer emits a status for a future, separately reviewed cleanup workflow.
"""
import json
from pathlib import Path
import sys

MANIFEST = Path('/etc/proxmox-power-manager/installation.json')
RECOVERY = Path('/var/lib/proxmox-power-manager/state.json')


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
    if Path(f'/etc/pve/lxc/{ctid}.conf').is_file():
        return 'present'
    return 'missing-unconfirmed'


if __name__ == '__main__':
    try:
        print(inspect())
    except (OSError, ValueError, KeyError) as exc:
        print(f'unknown: {exc}', file=sys.stderr)
        sys.exit(1)
