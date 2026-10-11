#!/usr/bin/env python3
"""Proxmox host power manager. No third-party Python dependencies."""
import argparse
import fcntl
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time

CONFIG = Path('/etc/proxmox-power-manager/config.json')
STATE = Path('/var/lib/proxmox-power-manager/state.json')
LOCK = Path('/run/proxmox-power-manager.lock')
DEFAULTS = dict(enabled=False, sleep_threshold=30, low_threshold=15,
                critical_threshold=8, normal_wake_minutes=15, low_wake_minutes=60,
                check_seconds=60, shutdown_timeout=120, force_stop_sleep=False, force_stop_low=False,
                ac_path='/sys/class/power_supply/ADP0/online',
                battery_path='/sys/class/power_supply/BAT0/capacity',
                manage_vms=True, critical_action='poweroff',
                minimum_restore_percent=0, charge_control_enabled=False,
                charge_lower_percent=70, charge_upper_percent=80)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', stream=sys.stdout)
log = logging.getLogger('ppm')


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(directory)
    finally: os.close(directory)


def validate(cfg):
    cfg = {**DEFAULTS, **cfg}
    for k in ('sleep_threshold','low_threshold','critical_threshold','normal_wake_minutes',
              'low_wake_minutes','check_seconds','shutdown_timeout','minimum_restore_percent'):
        if type(cfg[k]) is not int: raise ValueError(f'{k} must be integer')
    if type(cfg['charge_control_enabled']) is not bool: raise ValueError('charge_control_enabled must be boolean')
    for k in ('charge_lower_percent','charge_upper_percent'):
        if type(cfg[k]) is not int: raise ValueError(f'{k} must be integer')
    if not 0 <= cfg['charge_lower_percent'] < cfg['charge_upper_percent'] <= 100:
        raise ValueError('Invalid charge control thresholds')
    if type(cfg['enabled']) is not bool or type(cfg['manage_vms']) is not bool:
        raise ValueError('enabled/manage_vms must be boolean')
    if not (0 < cfg['critical_threshold'] < cfg['low_threshold'] < cfg['sleep_threshold'] <= 100):
        raise ValueError('Thresholds must satisfy critical < low < sleep <= 100')
    for k in ('normal_wake_minutes','low_wake_minutes'):
        if not 1 <= cfg[k] <= 1440: raise ValueError(f'Invalid {k}')
    if not 10 <= cfg['check_seconds'] <= 3600: raise ValueError('Invalid check_seconds')
    if not 30 <= cfg['shutdown_timeout'] <= 3600: raise ValueError('Invalid shutdown_timeout')
    if not 0 <= cfg['minimum_restore_percent'] <= 100: raise ValueError('Invalid minimum_restore_percent')
    for key in ('force_stop_sleep','force_stop_low'):
        if type(cfg[key]) is not bool: raise ValueError(f'{key} must be boolean')
    if cfg['critical_action'] not in ('poweroff','warn'): raise ValueError('Invalid critical_action')
    return cfg


def load_config():
    return validate(json.loads(CONFIG.read_text()) if CONFIG.exists() else {})


def read_int(path):
    return int(Path(path).read_text().strip())


def run(*args, timeout=180, check=True):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=check)


def running_cts():
    return [int(p[0]) for line in run('pct','list').stdout.splitlines()[1:]
            if (p := line.split()) and len(p) > 1 and p[1] == 'running']


def running_vms():
    output = run('qm','list').stdout.splitlines()[1:]
    return [int(p[0]) for line in output if (p := line.split()) and 'running' in p[1:]]


def ct_running(ct):
    return run('pct','status',str(ct),check=False).stdout.strip() == 'status: running'


def vm_running(vm):
    return run('qm','status',str(vm),check=False).stdout.strip() == 'status: running'


def state():
    if not STATE.exists(): return None
    data = json.loads(STATE.read_text())
    if 'vms' not in data: data['vms'] = []  # upgrade v0.2 state
    return data


def ac_online(cfg): return read_int(cfg['ac_path']) == 1


def stop_guests(cfg, force=False):
    saved = state()
    if saved is None:
        saved = dict(containers=running_cts(), vms=running_vms() if cfg['manage_vms'] else [],
                     created_at=int(time.time()))
        atomic_json(STATE, saved)  # write-ahead recovery record
    timeout = cfg['shutdown_timeout']
    for ct in saved['containers']:
        if ct_running(ct):
            log.info('Gracefully shutting down LXC %s', ct)
            try: run('pct','shutdown',str(ct),'--timeout',str(timeout),timeout=timeout+30)
            except (OSError,subprocess.SubprocessError) as e:
                log.error('LXC %s shutdown failed: %s',ct,e)
        if ct_running(ct):
            if not force or ac_online(cfg):
                log.error('LXC %s remains running; suspend aborted',ct)
                return False
            log.critical('Force stopping LXC %s after graceful timeout',ct)
            try: run('pct','stop',str(ct),'--timeout','30',timeout=45)
            except (OSError,subprocess.SubprocessError) as e: log.error('LXC %s force stop failed: %s',ct,e)
            if ct_running(ct): return False
    for vm in saved['vms']:
        if vm_running(vm):
            log.info('Gracefully shutting down VM %s',vm)
            try:
                run('qm','shutdown',str(vm),'--timeout',str(timeout),timeout=timeout+30)
            except (OSError,subprocess.SubprocessError) as e:
                log.error('VM %s shutdown failed: %s',vm,e)
        if vm_running(vm):
            if not force or ac_online(cfg):
                log.error('VM %s remains running; suspend aborted',vm)
                return False
            log.critical('Force stopping VM %s after graceful timeout',vm)
            try: run('qm','stop',str(vm),'--timeout','30',timeout=45)
            except (OSError,subprocess.SubprocessError) as e: log.error('VM %s force stop failed: %s',vm,e)
            if vm_running(vm): return False
    # Never suspend with unexpected running guests, including untracked VMs.
    if running_cts() or running_vms():
        log.error('Unstopped guests remain: CT=%s VM=%s',running_cts(),running_vms())
        return False
    return True


def restore_guests(cfg):
    saved = state()
    if saved is None: return
    if not ac_online(cfg): return
    if read_int(cfg['battery_path']) < cfg['minimum_restore_percent']:
        log.info('AC available; waiting for minimum battery charge before restore')
        return
    failed=[]
    for ct in saved['containers']:
        if not ct_running(ct):
            try: run('pct','start',str(ct))
            except (OSError,subprocess.SubprocessError) as e:
                log.error('LXC %s restore failed: %s',ct,e); failed.append(f'ct:{ct}')
    for vm in saved['vms']:
        if not vm_running(vm):
            try: run('qm','start',str(vm))
            except (OSError,subprocess.SubprocessError) as e:
                log.error('VM %s restore failed: %s',vm,e); failed.append(f'vm:{vm}')
    if not failed and all(ct_running(c) for c in saved['containers']) and all(vm_running(v) for v in saved['vms']):
        STATE.unlink(missing_ok=True)
        log.info('All recorded guests restored; state cleared')
        __import__('power_events').emit('GUESTS_RESTORED', reason='Электросеть восстановлена')
    else: log.error('Restore incomplete; state retained: %s',failed)


def status(cfg):
    return dict(ac_online=ac_online(cfg), battery_percent=read_int(cfg['battery_path']),
                enabled=cfg['enabled'], saved_state=state(),
                running_containers=running_cts(), running_vms=running_vms(),
                charge_control=__import__('charge_control').report(cfg),
                battery_info=__import__('battery_info').snapshot(cfg['battery_path'],
                    cfg['charge_upper_percent'] if cfg['charge_control_enabled'] else 100))


def critical(cfg, dry_run=False):
    log.warning('Critical battery threshold reached')
    if dry_run or not cfg['enabled']: return
    if not stop_guests(cfg):
        log.error('Guests did not shut down; poweroff requested as final battery safeguard')
    if ac_online(cfg):
        restore_guests(cfg); return
    if cfg['critical_action'] == 'poweroff':
        log.critical('Requesting system poweroff (automatic restart after AC restoration NOT guaranteed)')
        run('systemctl','poweroff','--no-block',timeout=15)


def cycle(cfg, dry_run=False):
    st = status(cfg)
    if not dry_run:
        try:
            from power_events import observe
            observe(st['ac_online'], st['battery_percent'], st['battery_info'].get('status'), st['charge_control'].get('mode'), cfg)
        except (OSError, ValueError) as exc:
            log.warning('Event monitoring unavailable: %s', exc)
    log.info('AC=%s battery=%s%% enabled=%s',st['ac_online'],st['battery_percent'],cfg['enabled'])
    if st['ac_online']:
        if not dry_run: restore_guests(cfg)
        return
    if not cfg['enabled']:
        if st['saved_state'] is not None:
            log.warning('Recovery state exists while automation is disabled; waiting for AC')
        return
    if st['saved_state'] is None and st['battery_percent'] > cfg['sleep_threshold']: return
    if st['battery_percent'] <= cfg['critical_threshold']:
        critical(cfg,dry_run); return
    minutes = cfg['low_wake_minutes'] if st['battery_percent'] <= cfg['low_threshold'] else cfg['normal_wake_minutes']
    if dry_run or not cfg['enabled']:
        log.info('Would stop guests and suspend for %s minutes',minutes); return
    current_percent = read_int(cfg['battery_path'])
    allow_force = (cfg['force_stop_low'] if current_percent <= cfg['low_threshold']
                   else cfg['force_stop_sleep'])
    if not stop_guests(cfg, force=allow_force): return
    if ac_online(cfg):
        log.info('AC returned before suspend'); restore_guests(cfg); return
    if read_int(cfg['battery_path']) <= cfg['critical_threshold']:
        critical(cfg); return
    # Not all systems support deep sleep. Let rtcwake select the available mode.
    __import__('power_events').emit('SLEEP_STARTED', battery_percent=read_int(cfg['battery_path']), duration_minutes=minutes, reason='Достигнут порог автоматического сна')
    log.info('Requesting RTC suspend for %s minutes',minutes)
    try:
        run('rtcwake','-m','mem','-s',str(minutes*60),timeout=minutes*60+300)
    except (OSError,subprocess.SubprocessError) as e:
        log.error('Suspend/wake failed: %s',e)
        return False
    __import__('power_events').emit('SERVER_WOKE', battery_percent=read_int(cfg['battery_path']), reason='Возврат из rtcwake')
    # A successful RTC wake requests an immediate full cycle, including AC and battery checks.
    # Do not recurse: the main loop reloads configuration and rechecks guest recovery state.
    return True


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['status','once','dry-run','run','restore'])
    args=parser.parse_args()
    cfg=load_config()
    if args.command=='status':
        print(json.dumps(status(cfg),indent=2)); return
    with open(LOCK,'w') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise SystemExit('Manager already running')
        if args.command=='restore': restore_guests(cfg); return
        if args.command in ('once','dry-run'):
            cycle(cfg,dry_run=args.command=='dry-run'); return
        while True:
            woke = False
            try: woke = cycle(load_config()) is True
            except Exception: log.exception('Cycle failed')
            if woke:
                log.info('RTC wake completed; checking AC and battery immediately')
                continue
            time.sleep(load_config()['check_seconds'])

if __name__=='__main__': main()
