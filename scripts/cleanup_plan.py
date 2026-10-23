#!/usr/bin/env python3
"""Read-only plan for uninstalling an owned Proxmox Power Manager installation.

This command does not stop services, change firewall rules, or remove files.
It only reports what a future, explicitly enabled cleanup could affect.
"""
import json
from pathlib import Path
import sys

import cleanup_watch

OPT_IN = Path('/etc/proxmox-power-manager/cleanup-policy.json')

HOST_FILES = [
    '/usr/local/bin/ppm',
    '/etc/systemd/system/proxmox-power-manager.service',
    '/etc/systemd/system/proxmox-power-manager-api.service',
    '/etc/systemd/system/proxmox-power-manager-cleanup.service',
    '/etc/systemd/system/proxmox-power-manager-cleanup.timer',
]
HOST_DIRS = [
    '/opt/proxmox-power-manager',
    '/etc/proxmox-power-manager',
    '/var/lib/proxmox-power-manager',
]


def plan():
    manifest = cleanup_watch.MANIFEST
    if not manifest.is_file():
        raise ValueError('Installation manifest not found')
    data = json.loads(manifest.read_text())
    ctid = data.get('web_ctid')
    if (data.get('schema') != 1 or type(ctid) is not int or
            not 100 <= ctid <= 999999 or
            data.get('web_ct_created_by_ppm') is not True or
            data.get('installation_complete') is not True):
        raise ValueError('Not a completed PPM-owned LXC installation')

    policy = json.loads(OPT_IN.read_text()) if OPT_IN.is_file() else {}
    if type(policy) is not dict:
        raise ValueError('Invalid cleanup policy')
    enabled = policy.get('automatic_cleanup', False) is True
    ac_path = Path('/sys/class/power_supply/ADP0/online')
    ac_connected = ac_path.is_file() and ac_path.read_text().strip() == '1'
    result = {
        'automatic_cleanup_enabled': enabled,
        'ac_connected': ac_connected,
        'eligible_for_cleanup': enabled and ac_connected and
            cleanup_watch.READY.is_file() and
            cleanup_watch.READY.read_text().strip() == str(ctid) and
            not cleanup_watch.RECOVERY.exists(),
        'mode': 'dry-run',
        'web_ctid': ctid,
        'confirmed_deleted': cleanup_watch.READY.is_file()
            and cleanup_watch.READY.read_text().strip() == str(ctid),
        'recovery_pending': cleanup_watch.RECOVERY.exists(),
        'candidate_files': [p for p in HOST_FILES if Path(p).exists()],
        'candidate_directories': [p for p in HOST_DIRS if Path(p).is_dir()],
        'firewall': 'Review PPM-owned API port 8765 rule manually',
        'changes_applied': False,
    }
    return result


if __name__ == '__main__':
    try:
        print(json.dumps(plan(), indent=2))
    except (OSError, ValueError) as exc:
        print(f'Cannot prepare cleanup plan: {exc}', file=sys.stderr)
        sys.exit(1)
