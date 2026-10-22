"""Protected file-backed TP-Link router DNS configuration."""
import ipaddress
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

CONFIG = Path('/etc/proxmox-power-manager/router.json')
DEFAULT = {'enabled': False, 'url': 'https://192.168.0.1/', 'normal_primary': '', 'normal_secondary': '', 'backup_primary': '', 'backup_secondary': ''}

def _load():
    try:
        data = json.loads(CONFIG.read_text())
        if not isinstance(data, dict):
            raise ValueError('Invalid router settings')
        return data
    except FileNotFoundError:
        return {}

def get_settings():
    data = {**DEFAULT, **_load()}
    data.pop('password', None)
    data['password_configured'] = bool(_load().get('password'))
    return data

def set_settings(payload):
    allowed = set(DEFAULT) | {'password'}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise ValueError('Unsupported router setting')
    data = {**DEFAULT, **_load()}
    for key, value in payload.items():
        if key == 'enabled':
            if type(value) is not bool:
                raise ValueError('enabled must be boolean')
        elif not isinstance(value, str) or len(value) > 512:
            raise ValueError('Invalid router setting: ' + key)
        if key != 'password' or value:
            data[key] = value
    parsed = urlsplit(data['url'])
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('Router URL must be HTTPS origin')
    try:
        addr = ipaddress.ip_address(parsed.hostname or '')
        if not addr.is_private:
            raise ValueError('Router must use private IP address')
    except ValueError:
        raise ValueError('Router URL must use private IPv4 address')
    for key in ('normal_primary', 'normal_secondary', 'backup_primary', 'backup_secondary'):
        if data[key]:
            try:
                if ipaddress.ip_address(data[key]).version != 4:
                    raise ValueError()
            except ValueError:
                raise ValueError(key + ' must be IPv4')
    if data['enabled'] and (not data.get('password') or not data['normal_primary'] or not data['backup_primary']):
        raise ValueError('Set router password and both primary DNS addresses before enabling')
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix('.tmp')
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG)
    finally:
        tmp.unlink(missing_ok=True)
    return get_settings()

def set_enabled(enabled):
    return set_settings({'enabled': enabled})
