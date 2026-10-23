#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || exit 1
if [[ -e /var/lib/proxmox-power-manager/state.json ]]; then
  echo 'Recovery state exists: restore guests before uninstalling'; exit 1
fi
read -rp 'Remove host agent and service? Config and data will be preserved [y/N]: ' answer
[[ "$answer" == 'y' ]] || exit 0
systemctl disable --now proxmox-power-manager-cleanup.timer || true
systemctl disable --now proxmox-power-manager.service || true
systemctl disable --now proxmox-power-manager-api.service || true
rm -f /etc/systemd/system/proxmox-power-manager.service /etc/systemd/system/proxmox-power-manager-api.service \
  /etc/systemd/system/proxmox-power-manager-cleanup.service /etc/systemd/system/proxmox-power-manager-cleanup.timer
systemctl daemon-reload
rm -rf /opt/proxmox-power-manager/agent /opt/proxmox-power-manager/cleanup
echo 'Host agent and lifecycle watcher removed. Web UI LXC, keys, config and logs remain for manual review.'
