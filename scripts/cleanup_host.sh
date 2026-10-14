#!/usr/bin/env bash
# Cleanup host-side PPM services after a managed web LXC has been removed.
# Never destroy any LXC, recovery state, user configuration, or secrets.
set -euo pipefail
[[ "$EUID" -eq 0 ]] || { echo 'Run as root' >&2; exit 1; }
base=/etc/proxmox-power-manager
ready=/var/lib/proxmox-power-manager/cleanup-ready
[[ -s "$ready" ]] || { echo 'No confirmed removal marker' >&2; exit 1; }
[[ ! -e /var/lib/proxmox-power-manager/state.json ]] || {
  echo 'Guest recovery pending; refusing cleanup' >&2; exit 1;
}
ctid="$(cat "$ready")"
[[ "$ctid" =~ ^[0-9]{3,6}$ ]] || exit 1
PPM_CTID="$ctid" python3 - <<'PY'
import json, os
from pathlib import Path
data=json.loads(Path('/etc/proxmox-power-manager/installation.json').read_text())
assert data.get('schema') == 1
assert data.get('web_ct_created_by_ppm') is True
assert data.get('web_ctid') == int(os.environ['PPM_CTID'])
assert not Path(f'/etc/pve/lxc/{os.environ["PPM_CTID"]}.conf').exists()
PY
# Fail closed if pmxcfs is unavailable.
[[ -s /etc/pve/.members ]] || exit 1
python3 - <<'PY'
import json
from pathlib import Path
assert json.loads(Path('/etc/pve/.members').read_text()).get('cluster', {}).get('quorate') is True
PY
systemctl disable --now proxmox-power-manager.service
systemctl disable --now proxmox-power-manager-api.service 2>/dev/null || true
echo "Managed LXC $ctid is absent: host services disabled."
echo 'Secrets, config and recovery files have been preserved.'
echo 'Run scripts/uninstall.sh manually for confirmed removal of installed binaries.'
