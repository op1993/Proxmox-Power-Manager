"""File-backed router DNS automation preference. Disabled by default."""
import json
import os
from pathlib import Path

CONFIG = Path('/etc/proxmox-power-manager/router.json')

def get_settings():
    try:
        data = json.loads(CONFIG.read_text())
        if not isinstance(data, dict):
            raise ValueError('Invalid router settings')
        return {'enabled': data.get('enabled') is True}
    except FileNotFoundError:
        return {'enabled': False}

def set_enabled(enabled):
    if type(enabled) is not bool:
        raise ValueError('enabled must be a boolean')
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(CONFIG.read_text())
        if not isinstance(data, dict):
            raise ValueError('Invalid router settings')
    except FileNotFoundError:
        data = {}
    data['enabled'] = enabled
    temp = CONFIG.with_name(CONFIG.name + '.tmp')
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, CONFIG)
    finally:
        temp.unlink(missing_ok=True)
    return {'enabled': enabled}
