#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root'; exit 1; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f /opt/proxmox-power-manager/agent/power_manager.py ]] || { echo 'Agent not installed'; exit 1; }
python3 -m py_compile "$ROOT/agent/power_manager.py" "$ROOT/agent/control.py" "$ROOT/agent/api.py" "$ROOT/web/server.py"
python3 -m unittest discover -s "$ROOT/tests" -v
if [[ -f /var/lib/proxmox-power-manager/state.json ]]; then
  echo 'Pending guest recovery state: refusing update until recovered'; exit 1
fi
if [[ -f /etc/proxmox-power-manager/config.json ]] && python3 -c 'import json; exit(json.load(open("/etc/proxmox-power-manager/config.json")).get("enabled",False))'; then
  :
else
  echo 'Disable automatic sleep in config before updating'; exit 1
fi
stamp="$(date +%Y%m%d%H%M%S)"
backup_dir="/var/backups/proxmox-power-manager/$stamp"
mkdir -p "$backup_dir"
cp -a /opt/proxmox-power-manager/agent "$backup_dir/"
cp -a /etc/proxmox-power-manager/config.json "/var/backups/proxmox-power-manager/$stamp/"
rollback() {
  echo 'Update failed; restoring previous host agent and systemd units' >&2
  cp -a "$backup_dir/agent/." /opt/proxmox-power-manager/agent/
  if [[ -d "$backup_dir/systemd" ]]; then
    cp -a "$backup_dir/systemd/." /etc/systemd/system/
  fi
  systemctl daemon-reload
  systemctl restart proxmox-power-manager.service || true
  if systemctl is-enabled --quiet proxmox-power-manager-api.service 2>/dev/null; then
    systemctl restart proxmox-power-manager-api.service || true
  fi
}
mkdir -p "$backup_dir/systemd"
for unit in proxmox-power-manager.service proxmox-power-manager-api.service; do
  if [[ -f "/etc/systemd/system/$unit" ]]; then
    cp -a "/etc/systemd/system/$unit" "$backup_dir/systemd/"
  fi
done
trap rollback ERR
install -m 0755 "$ROOT/agent/power_manager.py" /opt/proxmox-power-manager/agent/power_manager.py
install -m 0755 "$ROOT/agent/control.py" /opt/proxmox-power-manager/agent/control.py
install -m 0755 "$ROOT/agent/api.py" /opt/proxmox-power-manager/agent/api.py
if systemctl is-enabled --quiet proxmox-power-manager-api.service 2>/dev/null; then
  install -m 0644 "$ROOT/systemd/proxmox-power-manager-api.service" /etc/systemd/system/
  systemctl daemon-reload
  systemctl restart proxmox-power-manager-api.service
fi
systemctl restart proxmox-power-manager.service
systemctl is-active --quiet proxmox-power-manager.service
trap - ERR
echo "Host agent updated. Backup: /var/backups/proxmox-power-manager/$stamp"
echo 'Web UI is not updated by this script; its credentials and files are untouched.'
