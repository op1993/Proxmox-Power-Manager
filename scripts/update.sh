#!/usr/bin/env bash
# Update an installed Proxmox Power Manager, including its managed web LXC.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root on Proxmox' >&2; exit 1; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE=/opt/proxmox-power-manager
CFG=/etc/proxmox-power-manager
[[ -f "$BASE/agent/power_manager.py" ]] || { echo 'Host agent not installed' >&2; exit 1; }
command -v pct >/dev/null || { echo 'Proxmox pct command required' >&2; exit 1; }
python3 -m py_compile "$ROOT"/agent/{power_manager,control,api,charge_control,battery_info,power_events,event_history}.py "$ROOT"/web/{server,auth}.py "$ROOT"/scripts/{cleanup_watch,cleanup_plan}.py
if [[ -d "$ROOT/tests" ]]; then
  python3 -m unittest discover -s "$ROOT/tests" -v
fi
python3 - <<'PY'
import json,pathlib
cfg=json.loads(pathlib.Path('/etc/proxmox-power-manager/config.json').read_text())
if pathlib.Path('/var/lib/proxmox-power-manager/state.json').exists():
    raise SystemExit('Pending guest recovery: refusing update')
PY
ctid=""
if [[ -f "$CFG/installation.json" ]]; then
  ctid="$(python3 - <<'PY'
import json
d=json.load(open('/etc/proxmox-power-manager/installation.json'))
v=d.get('web_ctid')
if type(v) is not int or not 100 <= v <= 999999:
    raise SystemExit('Invalid web CTID in installation manifest')
print(v)
PY
)"
fi
if [[ -z "$ctid" && -f "$CFG/web.env" ]]; then
  echo 'Web configuration exists but managed CTID is unknown; refusing partial update.' >&2
  exit 1
fi
if [[ -n "$ctid" ]]; then
  pct status "$ctid" | grep -q 'running' || { echo "Web CT $ctid must be running" >&2; exit 1; }
  pct exec "$ctid" -- test -f /etc/proxmox-power-manager/auth.json || {
    echo 'Web auth config missing; refusing update' >&2; exit 1;
  }
fi
stamp="$(date +%Y%m%d%H%M%S)"
backup="/var/backups/proxmox-power-manager/$stamp"
mkdir -p "$backup/agent" "$backup/systemd" "$backup/cleanup"
if [[ -d "$BASE/cleanup" ]]; then cp -a "$BASE/cleanup/." "$backup/cleanup/"; fi
cp -a "$BASE/agent/." "$backup/agent/"
for unit in proxmox-power-manager.service proxmox-power-manager-api.service; do
  [[ ! -f "/etc/systemd/system/$unit" ]] || cp -a "/etc/systemd/system/$unit" "$backup/systemd/"
done
web_backup="/opt/proxmox-power-manager/web-backup-$stamp"
if [[ -n "$ctid" ]]; then
  pct exec "$ctid" -- cp -a /opt/proxmox-power-manager/web "$web_backup"
  pct exec "$ctid" -- cp -a /etc/systemd/system/proxmox-power-manager-web.service "$web_backup.service"
fi
rollback() {
  echo 'Update failed; rolling back application files' >&2
  cp -a "$backup/agent/." "$BASE/agent/"
  if [[ -d "$BASE/cleanup" ]]; then cp -a "$backup/cleanup/." "$BASE/cleanup/"; fi
  cp -a "$backup/systemd/." /etc/systemd/system/
  systemctl daemon-reload
  systemctl restart proxmox-power-manager.service || true
  if systemctl is-enabled --quiet proxmox-power-manager-api.service 2>/dev/null; then
    systemctl restart proxmox-power-manager-api.service || true
  fi
  if [[ -n "$ctid" ]]; then
    pct exec "$ctid" -- cp -a "$web_backup/." /opt/proxmox-power-manager/web/ || true
    pct exec "$ctid" -- cp -a "$web_backup.service" /etc/systemd/system/proxmox-power-manager-web.service || true
    pct exec "$ctid" -- systemctl daemon-reload || true
    pct exec "$ctid" -- systemctl restart proxmox-power-manager-web.service || true
  fi
}
trap rollback ERR
for f in power_manager.py control.py api.py simulator.py charge_control.py battery_info.py power_events.py event_history.py; do
  install -m 0755 "$ROOT/agent/$f" "$BASE/agent/$f"
done
for unit in proxmox-power-manager.service proxmox-power-manager-api.service proxmox-power-manager-cleanup.service proxmox-power-manager-cleanup.timer; do
  if [[ -f "/etc/systemd/system/$unit" ]]; then
    install -m 0644 "$ROOT/systemd/$unit" "/etc/systemd/system/$unit"
  fi
done
if [[ -f "$CFG/installation.json" ]]; then
  install -d -m 0755 "$BASE/cleanup"
  install -m 0755 "$ROOT/scripts/cleanup_watch.py" "$BASE/cleanup/cleanup_watch.py"
  install -m 0755 "$ROOT/scripts/cleanup_plan.py" "$BASE/cleanup/cleanup_plan.py"
fi
systemctl daemon-reload
systemctl restart proxmox-power-manager.service
systemctl is-active --quiet proxmox-power-manager.service
if systemctl is-enabled --quiet proxmox-power-manager-api.service 2>/dev/null; then
  systemctl restart proxmox-power-manager-api.service
  systemctl is-active --quiet proxmox-power-manager-api.service
fi
if [[ -n "$ctid" ]]; then
  for f in server.py auth.py index.html app.js; do
    pct push "$ctid" "$ROOT/web/$f" "/opt/proxmox-power-manager/web/$f"
  done
  pct push "$ctid" "$ROOT/systemd/proxmox-power-manager-web.service" /etc/systemd/system/proxmox-power-manager-web.service
  pct exec "$ctid" -- systemctl daemon-reload
  pct exec "$ctid" -- systemctl restart proxmox-power-manager-web.service
  pct exec "$ctid" -- systemctl is-active --quiet proxmox-power-manager-web.service
fi
install -m 0755 "$ROOT/scripts/ppm" /usr/local/bin/ppm
trap - ERR
echo "Update successful. Host backup: $backup"
if [[ -n "$ctid" ]]; then
  echo "Web LXC $ctid updated. Web backup: $web_backup"
fi
echo 'Configuration, authentication, API tokens and recovery state were not modified.'
