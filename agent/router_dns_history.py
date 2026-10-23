"""Bounded, credential-free router DNS transition history stored on the Proxmox host."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

HISTORY = Path('/var/lib/proxmox-power-manager/router-dns-history.json')
MAX_EVENTS = 200

def read():
    try:
        data = json.loads(HISTORY.read_text())
        return data[-MAX_EVENTS:] if isinstance(data, list) else []
    except (FileNotFoundError, ValueError, OSError):
        return []

def record(mode, status, reason, previous=None, current=None, error=None):
    event = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'mode': mode,
        'status': status,
        'reason': reason,
        'previous': previous,
        'current': current,
        'error': str(error)[:250] if error else None
    }
    events = (read() + [event])[-MAX_EVENTS:]
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    temp = HISTORY.with_suffix('.tmp')
    with open(temp, 'w') as f:
        json.dump(events, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(temp, 0o600)
    os.replace(temp, HISTORY)
