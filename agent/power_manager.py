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
import shutil

CONFIG = Path('/etc/proxmox-power-manager/config.json')
STATE = Path('/var/lib/proxmox-power-manager/state.json')
LOCK = Path('/run/proxmox-power-manager.lock')
HDD_STATE = Path('/var/lib/proxmox-power-manager/hdd-state.json')
DEFAULTS = dict(enabled=False, sleep_threshold=30, low_threshold=15,
                critical_threshold=8, normal_wake_minutes=15, low_wake_minutes=60,
                check_seconds=60, shutdown_timeout=120, force_stop_sleep=False, force_stop_low=False,
                ac_path='/sys/class/power_supply/ADP0/online',
                battery_path='/sys/class/power_supply/BAT0/capacity',
                manage_vms=True, critical_action='poweroff',
                minimum_restore_percent=0, charge_control_enabled=False,
                charge_upper_percent=80,
                hdd_spindown_enabled=False, hdd_disks=[])
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
    if type(cfg['charge_upper_percent']) is not int or not 1 <= cfg['charge_upper_percent'] <= 100:
        raise ValueError('Invalid charge upper threshold')
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
    if type(cfg['hdd_spindown_enabled']) is not bool: raise ValueError('hdd_spindown_enabled must be boolean')
    if type(cfg['hdd_disks']) is not list or len(cfg['hdd_disks']) > 16:
        raise ValueError('Invalid HDD selection')
    for disk in cfg['hdd_disks']:
        if type(disk) is not dict or set(disk) != {'device', 'mountpoint'}:
            raise ValueError('Invalid HDD entry')
        if not isinstance(disk['device'], str) or not disk['device'].startswith('/dev/disk/by-id/'):
            raise ValueError('HDD requires stable by-id path')
        if not isinstance(disk['mountpoint'], str) or not disk['mountpoint'].startswith('/') or disk['mountpoint'] == '/':
            raise ValueError('Invalid HDD mountpoint')
    if len({x['device'] for x in cfg['hdd_disks']}) != len(cfg['hdd_disks']):
        raise ValueError('Duplicate HDD')
    if cfg['hdd_spindown_enabled'] and not cfg['hdd_disks']:
        raise ValueError('Select at least one HDD')
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



def discover_hdds():
    """Return only mounted non-system rotational disks with stable identifiers."""
    import stat
    ls = json.loads(run('lsblk', '-J', '-b', '-o', 'NAME,PATH,TYPE,ROTA,SIZE,MODEL,MOUNTPOINTS').stdout)
    result = []
    for entry in ls['blockdevices']:
        if entry.get('type') != 'disk' or entry.get('rota') is not True:
            continue
        real = os.path.realpath(entry['path'])
        aliases = sorted(str(p) for p in Path('/dev/disk/by-id').glob('*')
                         if '-part' not in p.name and os.path.realpath(p) == real)
        if not aliases:
            continue
        for part in entry.get('children') or []:
            if part.get('type') != 'part':
                continue
            for mountpoint in part.get('mountpoints') or []:
                if not mountpoint or mountpoint == '/' or mountpoint.startswith(('/boot', '/etc/pve', '/var/lib/vz')):
                    continue
                if not Path(mountpoint).is_dir():
                    continue
                result.append(dict(device=aliases[0], mountpoint=mountpoint,
                                   model=(entry.get('model') or '').strip(), size=entry.get('size')))
    return result


def selected_disks(cfg):
    available = {(x['device'], x['mountpoint']): x for x in discover_hdds()}
    selected = []
    for disk in cfg['hdd_disks']:
        key = (disk['device'], disk['mountpoint'])
        if key not in available:
            raise RuntimeError('Selected HDD is missing or not safely mounted: ' + disk['device'])
        selected.append(disk)
    return selected


def mount_source(mountpoint):
    r = run('findmnt', '-n', '-o', 'SOURCE', '--mountpoint', mountpoint, check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def hdd_state():
    """Persist only disks successfully prepared by this manager."""
    if not HDD_STATE.exists():
        return {}
    data = json.loads(HDD_STATE.read_text())
    if not isinstance(data, dict):
        raise RuntimeError('Invalid HDD recovery state')
    return data


def disk_identity(device):
    """Reject a missing or changed physical device, even with a saved marker."""
    path = Path(device)
    if not path.exists() or not path.is_symlink():
        raise RuntimeError('Selected HDD missing: ' + device)
    real = os.path.realpath(device)
    if not real.startswith('/dev/') or not Path(real).exists():
        raise RuntimeError('Selected HDD unavailable: ' + device)
    return real


def hdd_stop(cfg):
    # Discovery intentionally requires mounted disks, so it must NOT run again
    # for a disk we safely unmounted during the previous suspend cycle.
    prepared = hdd_state()
    if not shutil.which('sg_start'):
        raise RuntimeError('Install sg3-utils on the Proxmox host')
    for disk in cfg['hdd_disks']:
        device, mountpoint = disk['device'], disk['mountpoint']
        identity = disk_identity(device)
        source = mount_source(mountpoint)
        previous = prepared.get(device)
        if previous is not None:
            if previous != {'device_realpath': identity, 'mountpoint': mountpoint}:
                raise RuntimeError('HDD identity or mountpoint changed: ' + device)
            if source:
                raise RuntimeError('Previously stopped HDD is unexpectedly mounted: ' + mountpoint)
            log.info('HDD already prepared for sleep: %s', device)
            continue
        # Validate newly selected disks against the original safe discovery.
        selected_disks({**cfg, 'hdd_disks': [disk]})
        if not source:
            raise RuntimeError('HDD is unmounted without a verified stop record: ' + mountpoint)
        run('sync', timeout=60)
        run('umount', mountpoint, timeout=60)
        if mount_source(mountpoint):
            raise RuntimeError('HDD still mounted: ' + mountpoint)
        run('sg_start', '--readonly', '--stop', device, timeout=45)
        prepared[device] = {'device_realpath': identity, 'mountpoint': mountpoint}
        atomic_json(HDD_STATE, prepared)
        log.info('HDD safely stopped: %s (%s)', device, mountpoint)
    return {'ok': True, 'stopped': len(cfg['hdd_disks'])}


def hdd_start(cfg):
    if not shutil.which('sg_start'):
        raise RuntimeError('Install sg3-utils on the Proxmox host')
    prepared = hdd_state()
    for disk in cfg['hdd_disks']:
        device, mountpoint = disk['device'], disk['mountpoint']
        identity = disk_identity(device)
        previous = prepared.get(device)
        if previous is not None and previous != {'device_realpath': identity, 'mountpoint': mountpoint}:
            raise RuntimeError('HDD identity or mountpoint changed: ' + device)
        if mount_source(mountpoint):
            # A mounted filesystem is not proof that the configured disk is
            # the source. Refuse to clear the recovery marker in that case.
            selected_disks({**cfg, 'hdd_disks': [disk]})
        else:
            if previous is None:
                raise RuntimeError('HDD unmounted without a verified stop record: ' + device)
            run('sg_start', '--readonly', '--start', device, timeout=45)
            run('mount', mountpoint, timeout=45)
            if not mount_source(mountpoint):
                raise RuntimeError('Failed to mount: ' + mountpoint)
            selected_disks({**cfg, 'hdd_disks': [disk]})
        if previous is not None:
            del prepared[device]
            atomic_json(HDD_STATE, prepared)
        log.info('HDD ready and mounted: %s (%s)', device, mountpoint)
    return {'ok': True, 'started': len(cfg['hdd_disks'])}


def restore_guests(cfg):
    saved = state()
    if saved is None: return
    if not ac_online(cfg): return
    if read_int(cfg['battery_path']) < cfg['minimum_restore_percent']:
        log.info('AC available; waiting for minimum battery charge before restore')
        return
    if cfg['hdd_spindown_enabled']:
        try: hdd_start(cfg)
        except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as exc:
            log.error('HDD restore failed; guests will not start: %s', exc)
            __import__('power_events').emit('HDD_ERROR', reason='Восстановление HDD не удалось: ' + str(exc))
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
    if not dry_run:
        __import__('charge_control').tick(cfg)
    st = status(cfg)
    if not dry_run:
        try:
            from power_events import observe
            observe(st['ac_online'], st['battery_percent'], st['battery_info'].get('status'), st['charge_control'].get('mode'), cfg)
        except (OSError, ValueError) as exc:
            log.warning('Event monitoring unavailable: %s', exc)
    router_ready = True
    if not dry_run:
        router_ready = __import__('router_dns_sync').sync(st['ac_online'])
    log.info('AC=%s battery=%s%% enabled=%s',st['ac_online'],st['battery_percent'],cfg['enabled'])
    if st['ac_online']:
        if not dry_run: restore_guests(cfg)
        return
    if not cfg['enabled']:
        if st['saved_state'] is not None:
            log.warning('Recovery state exists while automation is disabled; waiting for AC')
        return
    if st['saved_state'] is None and st['battery_percent'] > cfg['sleep_threshold']: return
    if not router_ready:
        log.error('Router DNS backup not confirmed; suspend aborted to preserve network DNS')
        return
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
    if cfg['hdd_spindown_enabled']:
        try: hdd_stop(cfg)
        except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as exc:
            log.error('HDD stop failed; suspend aborted: %s', exc)
            __import__('power_events').emit('HDD_ERROR', reason='Подготовка HDD к сну не удалась: ' + str(exc))
            return
    if ac_online(cfg):
        restore_guests(cfg); return
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
