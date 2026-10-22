"""Host-side router DNS transition hook. Uses managed LXC, no router secrets on host."""
import json
import logging
import subprocess
from pathlib import Path

LOG=logging.getLogger('ppm.router')
MANIFEST=Path('/etc/proxmox-power-manager/installation.json')
STATE=Path('/var/lib/proxmox-power-manager/router-dns-state.json')
from router_dns_history import record as record_event

def log_event(mode, status, reason, previous=None, current=None, error=None):
    try: record_event(mode, status, reason, previous, current, error)
    except (OSError, ValueError) as exc: LOG.warning('Router DNS history unavailable: %s', exc)

def sync(ac_online):
    """Return False if enabled automation failed to apply requested profile."""
    if not MANIFEST.exists(): return True
    try:
        manifest=json.loads(MANIFEST.read_text())
        ctid=manifest.get('web_ctid')
        if type(ctid) is not int: return True
        if subprocess.run(['pct','status',str(ctid)],capture_output=True,text=True,timeout=12).stdout.strip()!='status: running':
            LOG.warning('Router DNS Web LXC %s is not running',ctid)
            if STATE.exists() and not ac_online:
                try:
                    return json.loads(STATE.read_text()).get('mode') == 'backup'
                except (OSError, ValueError):
                    return False
            return True  # Not yet configured or AC has returned; do not start a guest implicitly.
        raw=subprocess.run(['pct','exec',str(ctid),'--','cat','/etc/proxmox-power-manager/router.json'],capture_output=True,text=True,timeout=15)
        if raw.returncode: return True  # Not configured yet.
        config=json.loads(raw.stdout)
        if config.get('enabled') is not True:
            STATE.unlink(missing_ok=True)
            return True
        mode='normal' if ac_online else 'backup'
        if STATE.exists():
            previous=json.loads(STATE.read_text())
            if previous.get('mode')==mode and previous.get('config')=={k:config.get(k) for k in ('url','normal_primary','normal_secondary','backup_primary','backup_secondary')}:
                return True
        previous_mode = None
        if STATE.exists():
            try: previous_mode = json.loads(STATE.read_text()).get('mode')
            except (OSError, ValueError): pass
        proc=subprocess.run(['pct','exec',str(ctid),'--','node','/opt/proxmox-power-manager/web/router_worker.js',mode],capture_output=True,text=True,timeout=110)
        if proc.returncode:
            LOG.error('Router DNS %s failed: %s',mode,(proc.stderr or proc.stdout)[-300:])
            log_event(mode, 'error', 'AC restored' if ac_online else 'AC lost', previous_mode, mode, (proc.stderr or proc.stdout)[-250:])
            return False
        STATE.parent.mkdir(parents=True,exist_ok=True)
        state={'mode':mode,'config':{k:config.get(k) for k in ('url','normal_primary','normal_secondary','backup_primary','backup_secondary')}}
        tmp=STATE.with_suffix('.tmp')
        tmp.write_text(json.dumps(state))
        tmp.replace(STATE)
        LOG.info('Router DNS profile applied: %s',mode)
        log_event(mode, 'success', 'AC restored' if ac_online else 'AC lost', previous_mode, mode)
        return True
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        LOG.error('Router DNS synchronization failed: %s',exc)
        log_event('normal' if ac_online else 'backup', 'error', 'Synchronization failure', error=exc)
        return False
