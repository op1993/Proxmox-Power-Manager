#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root on Proxmox'; exit 1; }
command -v pct >/dev/null || { echo 'This installer must run on a Proxmox host'; exit 1; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Installation helpers: use Proxmox's own storage and template metadata.
require_choice() {
  local value="$1" label="$2"
  [[ "$value" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "Invalid $label" >&2; exit 1; }
}
choose_default() {
  local prompt="$1" default="$2" response
  read -rp "$prompt [$default]: " response
  printf '%s' "${response:-$default}"
}
auto_ctid() {
  pvesh get /cluster/nextid --output-format json | tr -d '"[:space:]'
}
auto_host_ip() {
  ip -4 -o addr show scope global | awk '$2 ~ /^vmbr/ {split($4,a,"/"); print a[1]; exit}'
}
template_storage() {
  pvesm status --content vztmpl | awk 'NR>1 && $3=="active" {print $1; exit}'
}
root_storage() {
  pvesm status --content rootdir | awk 'NR>1 && $3=="active" {if($1=="local-lvm")preferred=$1; if(!first)first=$1} END {if(preferred)print preferred; else if(first)print first}'
}
select_template() {
  local store="$1" found candidate
  found="$(pveam list "$store" | awk '/debian-(12|13)-standard_/ {print $1}' | sort -V | tail -1)"
  if [[ -n "$found" ]]; then printf '%s' "$found"; return; fi
  echo "No Debian 12/13 template cached; refreshing template list..." >&2
  pveam update >&2
  candidate="$(pveam available --section system | awk '/debian-(12|13)-standard_/ {print $2}' | sort -V | tail -1)"
  [[ -n "$candidate" ]] || { echo "No Debian template available" >&2; return 1; }
  echo "Downloading $candidate into $store" >&2
  pveam download "$store" "$candidate" >&2
  printf '%s:vztmpl/%s' "$store" "$candidate"
}

install_host_agent() {
  install -d -m 0700 /etc/proxmox-power-manager
  printf '%s\n' 'feature/installer-v0.6' > /etc/proxmox-power-manager/update-ref
  chmod 0600 /etc/proxmox-power-manager/update-ref
  install -m 0755 "$ROOT/scripts/ppm" /usr/local/bin/ppm
  mkdir -p /opt/proxmox-power-manager/agent /etc/proxmox-power-manager /var/lib/proxmox-power-manager
  install -m 0755 "$ROOT/agent/power_manager.py" /opt/proxmox-power-manager/agent/power_manager.py
  install -m 0755 "$ROOT/agent/control.py" /opt/proxmox-power-manager/agent/control.py
  install -m 0755 "$ROOT/agent/api.py" /opt/proxmox-power-manager/agent/api.py
  install -m 0755 "$ROOT/agent/simulator.py" /opt/proxmox-power-manager/agent/simulator.py
  install -m 0755 "$ROOT/agent/charge_control.py" /opt/proxmox-power-manager/agent/charge_control.py
  install -m 0755 "$ROOT/agent/battery_info.py" /opt/proxmox-power-manager/agent/battery_info.py
  install -m 0755 "$ROOT/agent/power_events.py" /opt/proxmox-power-manager/agent/power_events.py
  install -m 0755 "$ROOT/agent/router_dns_sync.py" /opt/proxmox-power-manager/agent/router_dns_sync.py
  install -m 0755 "$ROOT/agent/event_history.py" /opt/proxmox-power-manager/agent/event_history.py
  if [[ ! -f /etc/proxmox-power-manager/config.json ]]; then
    install -m 0600 "$ROOT/config/config.example.json" /etc/proxmox-power-manager/config.json
  fi
  install -m 0644 "$ROOT/systemd/proxmox-power-manager.service" /etc/systemd/system/proxmox-power-manager.service
  systemctl daemon-reload
  systemctl enable proxmox-power-manager.service
  systemctl restart proxmox-power-manager.service
}

echo 'Proxmox Power Manager installer'
echo '1) Agent only'
echo '2) Agent + new LXC web UI (Debian 12/13 template)'
echo '3) Agent + existing Debian LXC web UI'
read -rp 'Choose [1-3]: ' mode
[[ "$mode" =~ ^[123]$ ]] || exit 1
if [[ "$mode" == 1 ]]; then
  install_host_agent
  echo 'Agent installed. Automatic sleep is disabled by default on first install.'
  exit 0
fi
command -v openssl >/dev/null || { echo 'Missing openssl'; exit 1; }
default_ip="$(auto_host_ip)"
[[ -n "$default_ip" ]] || { echo "Could not detect vmbr IPv4; supply host IP." >&2; }
hostip="$(choose_default 'Proxmox host LAN IP reachable from LXC' "$default_ip")"
[[ "$hostip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Use IPv4 LAN address'; exit 1; }
if [[ "$mode" == 2 ]]; then
  command -v pvesh >/dev/null || { echo 'Missing pvesh'; exit 1; }
  command -v pvesm >/dev/null || { echo 'Missing pvesm'; exit 1; }
  command -v pveam >/dev/null || { echo 'Missing pveam'; exit 1; }
  read -rp 'Setup [1=automatic, 2=advanced] (default 1): ' setup
  setup="${setup:-1}"
  [[ "$setup" =~ ^[12]$ ]] || exit 1
  suggested_ctid="$(auto_ctid)"
  [[ "$suggested_ctid" =~ ^[0-9]{3,6}$ ]] || { echo 'Unable to select CTID'; exit 1; }
  suggested_template_storage="$(template_storage)"
  suggested_root_storage="$(root_storage)"
  [[ -n "$suggested_template_storage" && -n "$suggested_root_storage" ]] || {
    echo 'No active template or rootdir storage found' >&2; exit 1;
  }
  ctid="$suggested_ctid"
  template_store="$suggested_template_storage"
  storage="$suggested_root_storage"
  bridge="vmbr0"
  cores=1; memory=256; disk=4
  if [[ "$setup" == 2 ]]; then
    ctid="$(choose_default 'New CTID' "$ctid")"
    template_store="$(choose_default 'Template storage' "$template_store")"
    storage="$(choose_default 'Rootfs storage' "$storage")"
    bridge="$(choose_default 'Network bridge' "$bridge")"
    cores="$(choose_default 'CPU cores' "$cores")"
    memory="$(choose_default 'Memory (MiB)' "$memory")"
    disk="$(choose_default 'Disk (GiB)' "$disk")"
  fi
  [[ "$ctid" =~ ^[0-9]{3,6}$ ]] || { echo 'Invalid CTID'; exit 1; }
  require_choice "$template_store" 'template storage'
  require_choice "$storage" 'root storage'
  require_choice "$bridge" 'bridge'
  [[ "$cores" =~ ^[0-9]+$ && "$cores" -ge 1 && "$cores" -le 16 ]] || exit 1
  [[ "$memory" =~ ^[0-9]+$ && "$memory" -ge 256 && "$memory" -le 16384 ]] || exit 1
  [[ "$disk" =~ ^[0-9]+$ && "$disk" -ge 4 && "$disk" -le 256 ]] || exit 1
  if pct status "$ctid" >/dev/null 2>&1; then echo 'CTID already exists'; exit 1; fi
  ip link show "$bridge" >/dev/null || { echo 'Bridge not found'; exit 1; }
  pvesm status --content rootdir | awk 'NR>1 {print $1}' | grep -Fxq "$storage" || { echo 'Invalid rootdir storage'; exit 1; }
  pvesm status --content vztmpl | awk 'NR>1 {print $1}' | grep -Fxq "$template_store" || { echo 'Invalid template storage'; exit 1; }
  template="$(select_template "$template_store")"
  echo "Will create CT $ctid using $template, $storage ($disk GiB), $memory MiB RAM, $cores CPU on $bridge"
  read -rp 'Create this LXC? [y/N]: ' confirmed
  [[ "$confirmed" =~ ^[Yy]$ ]] || exit 0
  if [[ -e /etc/proxmox-power-manager/installation.json ]]; then
    echo 'An installation manifest already exists. Refusing to create a second managed container.' >&2
    exit 1
  fi
  # EXIT catches explicit 'exit 1' as well as failed commands.
  managed_install_complete=0
  on_managed_install_exit() {
    local status=$?
    if [[ "$managed_install_complete" != 1 ]]; then
      echo "Managed LXC $ctid installation did not complete (exit $status)." >&2
      echo "The container is preserved; review /etc/proxmox-power-manager/installation.json." >&2
    fi
  }
  trap on_managed_install_exit EXIT
  pct create "$ctid" "$template" --hostname ppm-web --ostype debian --unprivileged 1 --cores "$cores" --memory "$memory" --swap 256 --rootfs "${storage}:${disk}" --net0 "name=eth0,bridge=${bridge},ip=dhcp" --onboot 1 --features nesting=0
  install -d -m 0700 /etc/proxmox-power-manager
  # Register the CT before installing host services. A failed install stays disarmed.
  PPM_CTID="$ctid" python3 - <<'PYMANIFEST'
import json, os, pathlib
p = pathlib.Path('/etc/proxmox-power-manager/installation.json')
p.write_text(json.dumps({'schema': 1, 'web_ctid': int(os.environ['PPM_CTID']),
                         'web_ct_created_by_ppm': True, 'installation_complete': False}, indent=2) + '\n')
p.chmod(0o600)
PYMANIFEST
  install -d -m 0755 /opt/proxmox-power-manager/cleanup
  install -m 0755 "$ROOT/scripts/cleanup_watch.py" /opt/proxmox-power-manager/cleanup/cleanup_watch.py
  install -m 0644 "$ROOT/systemd/proxmox-power-manager-cleanup.service" /etc/systemd/system/
  install -m 0644 "$ROOT/systemd/proxmox-power-manager-cleanup.timer" /etc/systemd/system/
  systemctl daemon-reload
  install_host_agent
  pct start "$ctid"
  echo "Waiting for CT $ctid network initialization..."
  for attempt in $(seq 1 30); do
    if pct exec "$ctid" -- sh -c 'getent hosts deb.debian.org >/dev/null' >/dev/null 2>&1; then break; fi
    sleep 2
  done
else
  read -rp 'Existing Debian CTID: ' ctid
  [[ "$ctid" =~ ^[0-9]{3,6}$ ]] || exit 1
  pct status "$ctid" | grep -q 'running' || { echo 'Container must be running'; exit 1; }
  read -rp 'Existing container will receive web files and Python runtime. Continue? [y/N]: ' answer
  [[ "$answer" == 'y' ]] || exit 1
fi
if [[ "$mode" == 3 ]]; then
  install_host_agent
fi
pct exec "$ctid" -- sh -c 'command -v apt-get >/dev/null && test -f /etc/debian_version' || { echo 'Requires Debian LXC'; exit 1; }
if ! pct exec "$ctid" -- sh -c 'getent hosts deb.debian.org >/dev/null'; then
  echo 'Container DNS/network unavailable; cannot install dependencies' >&2
  exit 1
fi
pct exec "$ctid" -- apt-get update
pct exec "$ctid" -- apt-get install -y python3 ca-certificates openssl
pct exec "$ctid" -- mkdir -p /opt/proxmox-power-manager/web /etc/proxmox-power-manager
for f in server.py auth.py oidc.py oidc_discovery.py router_settings.py index.html app.js; do pct push "$ctid" "$ROOT/web/$f" "/opt/proxmox-power-manager/web/$f"; done
for f in package.json router_dns.js router_worker.js; do pct push "$ctid" "$ROOT/web/$f" "/opt/proxmox-power-manager/web/$f"; done
pct push "$ctid" "$ROOT/scripts/install_router_dependencies.sh" /tmp/ppm-install-router-deps.sh
pct exec "$ctid" -- bash /tmp/ppm-install-router-deps.sh
pct exec "$ctid" -- rm -f /tmp/ppm-install-router-deps.sh
KEY_DIR=/etc/proxmox-power-manager
# Private HTTPS API; certificate contains the Proxmox LAN IP as an IP SAN.
if [[ -f "$KEY_DIR/api.crt" ]]; then
  if ! openssl x509 -in "$KEY_DIR/api.crt" -noout -ext subjectAltName | grep -Fq "IP Address:$hostip"; then
    echo 'Existing API certificate does not match selected IP. Keep existing API address or rotate cert manually.' >&2
    exit 1
  fi
else
  openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 365 \
    -keyout "$KEY_DIR/api.key" -out "$KEY_DIR/api.crt" \
    -subj '/CN=Proxmox Power Manager API' \
    -addext "subjectAltName=IP:$hostip" >/dev/null 2>&1
  chmod 600 "$KEY_DIR/api.key"
fi
if [[ ! -f "$KEY_DIR/api-token" ]]; then
  python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > "$KEY_DIR/api-token"
  chmod 600 "$KEY_DIR/api-token"
fi
printf 'PPM_API_BIND=%s\nPPM_API_PORT=8765\n' "$hostip" > "$KEY_DIR/api.env"
chmod 600 "$KEY_DIR/api.env"
install -m 0644 "$ROOT/systemd/proxmox-power-manager-api.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now proxmox-power-manager-api.service
systemctl restart proxmox-power-manager-api.service
pct push "$ctid" "$KEY_DIR/api-token" /etc/proxmox-power-manager/api-token
pct push "$ctid" "$KEY_DIR/api.crt" /etc/proxmox-power-manager/api.crt
pct exec "$ctid" -- chmod 600 /etc/proxmox-power-manager/api-token
# Authentication config lives inside the LXC, not in the Git checkout.
AUTH_FILE="$KEY_DIR/auth-${ctid}.json"
if ! pct exec "$ctid" -- test -f /etc/proxmox-power-manager/auth.json; then
  password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  PPM_GENERATED_PASSWORD="$password" python3 - "$AUTH_FILE" "$ROOT/web" <<'PYAUTH'
import importlib.util, json, os, pathlib, secrets, sys
spec = importlib.util.spec_from_file_location('ppm_auth', pathlib.Path(sys.argv[2]) / 'auth.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
data = {'username': 'admin', 'password_hash': module.password_hash(os.environ['PPM_GENERATED_PASSWORD']),
        'session_secret': secrets.token_hex(32), 'oidc': {'enabled': False, 'issuer_url': '', 'client_id': '', 'client_secret_env': 'PPM_OIDC_CLIENT_SECRET'}}
pathlib.Path(sys.argv[1]).write_text(json.dumps(data, indent=2) + '\n')
PYAUTH
  chmod 600 "$AUTH_FILE"
  pct push "$ctid" "$AUTH_FILE" /etc/proxmox-power-manager/auth.json
  pct exec "$ctid" -- chmod 600 /etc/proxmox-power-manager/auth.json
  rm -f "$AUTH_FILE"
  echo "Initial web username: admin"
  echo "Initial web password (SAVE NOW, displayed once): $password"
  unset password
else
  echo 'Existing web credentials preserved.'
fi
printf 'PPM_API_URL=https://%s:8765\nPPM_API_TOKEN_FILE=/etc/proxmox-power-manager/api-token\nPPM_API_CA=/etc/proxmox-power-manager/api.crt\nPPM_PORT=8080\nPPM_AUTH_CONFIG=/etc/proxmox-power-manager/auth.json\nPPM_HTTPS=0\n' "$hostip" > "$KEY_DIR/web.env"
chmod 600 "$KEY_DIR/web.env"
pct push "$ctid" "$KEY_DIR/web.env" /etc/proxmox-power-manager/web.env
pct exec "$ctid" -- chmod 600 /etc/proxmox-power-manager/web.env
pct push "$ctid" "$ROOT/systemd/proxmox-power-manager-web.service" /etc/systemd/system/proxmox-power-manager-web.service
pct exec "$ctid" -- systemctl daemon-reload
pct exec "$ctid" -- systemctl enable --now proxmox-power-manager-web.service
pct exec "$ctid" -- systemctl is-active --quiet proxmox-power-manager-web.service || {
  echo 'Web service failed to start; inspect container logs' >&2; exit 1;
}
# Permit only the web container to reach the host API through Proxmox firewall.
# Do not alter global firewall policy or create broad LAN allow rules.
configure_api_firewall() {
  local ct_ip node existing
  ct_ip="$(pct exec "$ctid" -- ip -4 -o addr show dev eth0 | awk '{split($4,a,"/"); print a[1]; exit}')"
  [[ "$ct_ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
    echo 'Cannot determine LXC IPv4 for firewall rule' >&2; return 1;
  }
  node="$(hostname -s)"
  existing="$(pvesh get "/nodes/$node/firewall/rules" --output-format json)"
  if PPM_SOURCE="$ct_ip/32" python3 -c '
import json,os,sys
rules=json.load(sys.stdin)
sys.exit(0 if any(
    x.get("type")=="in" and x.get("action")=="ACCEPT"
    and x.get("proto")=="tcp" and str(x.get("dport"))=="8765"
    and x.get("source")==os.environ["PPM_SOURCE"]
    and x.get("enable",1) in (1,True,"1")
    for x in rules
) else 1)' <<< "$existing"; then
    echo "Host API firewall rule already exists for $ct_ip"
  else
    pvesh create "/nodes/$node/firewall/rules" \
      --type in --action ACCEPT --proto tcp --source "$ct_ip/32" \
      --dport 8765 --enable 1 --comment "PPM Web LXC $ctid"
    echo "Allowed Host API TCP/8765 from $ct_ip only"
  fi
}
configure_api_firewall
echo 'Web UI installed. Access port 8080 on the LXC IP (LAN only).'
echo 'Testing API connectivity from the container...'
if pct exec "$ctid" -- python3 -c 'import os,ssl,urllib.request; p="/etc/proxmox-power-manager/"; url=open(p+"web.env").read().split("PPM_API_URL=",1)[1].splitlines()[0]; token=open(p+"api-token").read().strip(); req=urllib.request.Request(url+"/v1/status",headers={"Authorization":"Bearer "+token}); print("API status:",urllib.request.urlopen(req,context=ssl.create_default_context(cafile=p+"api.crt"),timeout=10).status)'; then
  echo 'API connection verified.'
else
  echo 'ERROR: API connection failed. Check IP, firewall and API service logs.' >&2
  exit 1
fi
if [[ "$mode" == 2 ]]; then
  python3 - <<'PYMANIFEST_DONE'
import json
from pathlib import Path
p = Path('/etc/proxmox-power-manager/installation.json')
data = json.loads(p.read_text())
data['installation_complete'] = True
p.write_text(json.dumps(data, indent=2) + '\n')
p.chmod(0o600)
PYMANIFEST_DONE
  systemctl enable --now proxmox-power-manager-cleanup.timer
  managed_install_complete=1
  trap - EXIT
fi
echo "Authentication settings: /etc/proxmox-power-manager/auth.json (inside CT $ctid)"
echo 'WARNING: Plain HTTP on port 8080. Restrict access to LAN; use HTTPS reverse proxy for remote access.'
echo 'WARNING: API token grants privileged power-manager settings access. Keep it secret; restrict TCP/8765 to the web LXC IP with a firewall.'
