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
mkdir -p "/var/backups/proxmox-power-manager/$stamp"
cp -a /opt/proxmox-power-manager/agent "/var/backups/proxmox-power-manager/$stamp/"
cp -a /etc/proxmox-power-manager/config.json "/var/backups/proxmox-power-manager/$stamp/"
install -m 0755 "$ROOT/agent/power_manager.py" /opt/proxmox-power-manager/agent/power_manager.py
install -m 0755 "$ROOT/agent/control.py" /opt/proxmox-power-manager/agent/control.py
install -m 0755 "$ROOT/agent/api.py" /opt/proxmox-power-manager/agent/api.py
if systemctl is-enabled --quiet proxmox-power-manager-api.service 2>/dev/null; then
  install -m 0644 "$ROOT/systemd/proxmox-power-manager-api.service" /etc/systemd/system/
  systemctl daemon-reload
  systemctl restart proxmox-power-manager-api.service
fi
systemctl restart proxmox-power-manager.service
systemctl is-active --quiet proxmox-power-manager.service || { echo 'Agent unhealthy: restore backup manually from /var/backups/proxmox-power-manager/'"$stamp"; exit 1; }
echo "Host agent updated. Backup: /var/backups/proxmox-power-manager/$stamp"
echo 'Web UI update requires copying web files to its LXC and restarting the web service.'
