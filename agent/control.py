#!/usr/bin/env python3
"""Restricted SSH command interface for the web UI. Never accepts shell commands."""
import base64, fcntl, json, os, pathlib, subprocess, sys
import importlib.util
CONFIG = pathlib.Path('/etc/proxmox-power-manager/config.json')
STATE = pathlib.Path('/var/lib/proxmox-power-manager/state.json')
LOCK = pathlib.Path('/run/proxmox-power-manager-config.lock')
FIELDS = {'enabled': bool, 'sleep_threshold': int, 'low_threshold': int, 'critical_threshold': int,
          'normal_wake_minutes': int, 'low_wake_minutes': int, 'check_seconds': int, 'shutdown_timeout': int,
          'manage_vms': bool, 'charge_control_enabled': bool, 'force_stop_sleep': bool, 'force_stop_low': bool,
          'charge_upper_percent': int,
          'hdd_spindown_enabled': bool, 'hdd_disks': list, 'critical_action': str, 'minimum_restore_percent': int}

def output(data):
    print(json.dumps(data, ensure_ascii=False))

def read_config():
    return json.loads(CONFIG.read_text())

def validate(old, changes):
    if not isinstance(changes, dict) or set(changes) - set(FIELDS):
        raise ValueError('Unsupported configuration field')
    new = dict(old)
    for key, val in changes.items():
        typ = FIELDS[key]
        if type(val) is not typ: raise ValueError(f'Invalid type: {key}')
        new[key] = val
    if not 1 <= new.get('charge_upper_percent',80) <= 100:
        raise ValueError('Invalid charge upper threshold')
    if not (0 < new['critical_threshold'] < new['low_threshold'] < new['sleep_threshold'] <= 100):
        raise ValueError('Thresholds must satisfy critical < low < sleep <= 100')
    for key in ('normal_wake_minutes','low_wake_minutes','check_seconds','shutdown_timeout'):
        if not (1 <= new[key] <= (1440 if 'minutes' in key else 3600)):
            raise ValueError(f'Out of range: {key}')
    import power_manager
    power_manager.validate(new)
    if 'hdd_disks' in changes:
        choices = {(d['device'], d['mountpoint']) for d in power_manager.discover_hdds()}
        for disk in new['hdd_disks']:
            if (disk['device'], disk['mountpoint']) not in choices and disk not in old.get('hdd_disks', []):
                raise ValueError('HDD not in discovered devices')
    if new.get('critical_action','poweroff') not in ('poweroff','warn'): raise ValueError('Invalid critical action')
    if not 0 <= new.get('minimum_restore_percent',0) <= 100: raise ValueError('Invalid restore threshold')
    return new

def execute(action, changes=None):
    if action == 'status':
        proc = subprocess.run(['/usr/bin/python3','/opt/proxmox-power-manager/agent/power_manager.py','status'], capture_output=True, text=True, timeout=25)
        if proc.returncode: raise RuntimeError('Status unavailable')
        return json.loads(proc.stdout)
    if action == 'hdd-list':
        import power_manager
        return {'disks': power_manager.discover_hdds()}
    if action == 'hdd-start':
        if changes not in ({}, None): raise ValueError('Unexpected payload')
        import power_manager
        return power_manager.hdd_start(power_manager.load_config())
    if action == 'telegram-config':
        from telegram_notify import settings
        return settings()
    if action == 'telegram-update':
        from telegram_notify import save
        return save(changes)
    if action == 'telegram-test':
        from telegram_notify import send
        return {'ok':send('Proxmox Power Manager: Telegram test',force=True)}
    if action == 'router-history':
        from router_dns_history import read
        return {'events': list(reversed(read()))}
    if action == 'history':
        from event_history import today
        return today()
    if action == 'history-date':
        from event_history import for_date
        if not isinstance(changes, dict) or set(changes) != {'date'}:
            raise ValueError('Expected date')
        return for_date(changes['date'])
    if action == 'config':
        return read_config()
    if action == 'update':
        with open(LOCK,'w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            cfg = validate(read_config(), changes)
            tmp = CONFIG.with_suffix('.tmp')
            with open(tmp,'w') as f:
                json.dump(cfg,f,indent=2); f.flush(); os.fsync(f.fileno())
            os.chmod(tmp,0o600); os.replace(tmp,CONFIG)
        return {'ok':True, 'config':cfg}
    if action == 'dry-run':
        from simulator import simulate
        agent_path = pathlib.Path('/opt/proxmox-power-manager/agent/power_manager.py')
        spec = importlib.util.spec_from_file_location('ppm_agent_preview', agent_path)
        agent = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(agent)
        cfg = agent.load_config()
        return simulate(cfg, agent.status(cfg), changes or {})
    raise ValueError('Action not permitted')

if __name__ == '__main__':
    raise SystemExit('Use agent/api.py instead of SSH control')
