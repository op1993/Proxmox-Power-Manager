"""Host-side router DNS transition hook. Uses managed LXC, no router secrets on host."""
import json
import logging
import subprocess
from pathlib import Path

LOG=logging.getLogger('ppm.router')
MANIFEST=Path('/etc/proxmox-power-manager/installation.json')
STATE=Path('/var/lib/proxmox-power-manager/router-dns-state.json')

def sync(ac_online):
    """Return False if enabled automation failed to apply requested profile."""
    if not MANIFEST.exists(): return True
    try:
        manifest=json.loads(MANIFEST.read_text())
        ctid=manifest.get('web_ctid')
        if type(ctid) is not int: return True
        if subprocess.run(['pct','status',str(ctid)],capture_output=True,text=True,timeout=12).stdout.strip()!='status: running':
            LOG.warning('Router DNS Web LXC %s is not running',ctid)
            return True  # Cannot inspect its enabled flag; never start a guest implicitly.
        raw=subprocess.run(['pct','exec',str(ctid),'--','cat','/etc/proxmox-power-manager/router.json'],capture_output=True,text=True,timeout=15)
        if raw.returncode: return True  # Not configured yet.
        config=json.loads(raw.stdout)
        if config.get('enabled') is not True: return True
        mode='normal' if ac_online else 'backup'
        if STATE.exists():
            previous=json.loads(STATE.read_text())
            if previous.get('mode')==mode and previous.get('config')=={k:config.get(k) for k in ('url','normal_primary','normal_secondary','backup_primary','backup_secondary')}:
                return True
        proc=subprocess.run(['pct','exec',str(ctid),'--','node','/opt/proxmox-power-manager/web/router_worker.js',mode],capture_output=True,text=True,timeout=110)
        if proc.returncode:
            LOG.error('Router DNS %s failed: %s',mode,(proc.stderr or proc.stdout)[-300:])
            return False
        STATE.parent.mkdir(parents=True,exist_ok=True)
        state={'mode':mode,'config':{k:config.get(k) for k in ('url','normal_primary','normal_secondary','backup_primary','backup_secondary')}}
        tmp=STATE.with_suffix('.tmp')
        tmp.write_text(json.dumps(state))
        tmp.replace(STATE)
        LOG.info('Router DNS profile applied: %s',mode)
        return True
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        LOG.error('Router DNS synchronization failed: %s',exc)
        return False
