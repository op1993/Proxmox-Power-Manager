#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root on Proxmox'; exit 1; }
command -v pct >/dev/null || { echo 'This installer must run on a Proxmox host'; exit 1; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo 'Proxmox Power Manager installer'
echo '1) Agent only'
echo '2) Agent + new LXC web UI (Debian 12/13 template)'
echo '3) Agent + existing Debian LXC web UI'
read -rp 'Choose [1-3]: ' mode
[[ "$mode" =~ ^[123]$ ]] || exit 1
mkdir -p /opt/proxmox-power-manager/agent /etc/proxmox-power-manager /var/lib/proxmox-power-manager
install -m 0755 "$ROOT/agent/power_manager.py" /opt/proxmox-power-manager/agent/power_manager.py
install -m 0755 "$ROOT/agent/control.py" /opt/proxmox-power-manager/agent/control.py
install -m 0755 "$ROOT/agent/api.py" /opt/proxmox-power-manager/agent/api.py
if [[ ! -f /etc/proxmox-power-manager/config.json ]]; then
  install -m 0600 "$ROOT/config/config.example.json" /etc/proxmox-power-manager/config.json
fi
install -m 0644 "$ROOT/systemd/proxmox-power-manager.service" /etc/systemd/system/proxmox-power-manager.service
systemctl daemon-reload
systemctl enable proxmox-power-manager.service
systemctl restart proxmox-power-manager.service
if [[ "$mode" == 1 ]]; then
  echo 'Agent installed. Automatic sleep is disabled by default on first install.'
  exit 0
fi
command -v openssl >/dev/null || { echo 'Missing openssl'; exit 1; }
read -rp 'Proxmox host LAN IP reachable from LXC: ' hostip
[[ "$hostip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Use IPv4 LAN address'; exit 1; }
if [[ "$mode" == 2 ]]; then
  read -rp 'New CTID: ' ctid
  [[ "$ctid" =~ ^[0-9]{3,6}$ ]] || exit 1
  if pct status "$ctid" >/dev/null 2>&1; then echo 'CTID already exists'; exit 1; fi
  echo 'Available Debian templates:'
  pveam list local | grep -E 'debian-(12|13).*standard' || true
  read -rp 'Template volume (e.g. local:vztmpl/debian-13-standard_...tar.zst): ' template
  [[ "$template" =~ ^[a-zA-Z0-9_-]+:vztmpl/debian-(12|13)-standard_[a-zA-Z0-9._+-]+\.tar\.(zst|gz|xz)$ ]] || { echo 'Invalid template'; exit 1; }
  read -rp 'Rootfs storage [local-lvm]: ' storage
  storage="${storage:-local-lvm}"
  [[ "$storage" =~ ^[a-zA-Z0-9_-]+$ ]] || exit 1
  read -rp 'Network bridge [vmbr0]: ' bridge
  bridge="${bridge:-vmbr0}"
  [[ "$bridge" =~ ^[a-zA-Z0-9_-]+$ ]] || exit 1
  pct create "$ctid" "$template" --hostname ppm-web --ostype debian --unprivileged 1 --cores 1 --memory 256 --swap 256 --rootfs "${storage}:4" --net0 "name=eth0,bridge=${bridge},ip=dhcp" --onboot 1 --features nesting=0
  pct start "$ctid"
else
  read -rp 'Existing Debian CTID: ' ctid
  [[ "$ctid" =~ ^[0-9]{3,6}$ ]] || exit 1
  pct status "$ctid" | grep -q 'running' || { echo 'Container must be running'; exit 1; }
  read -rp 'Existing container will receive web files and SSH client. Continue? [y/N]: ' answer
  [[ "$answer" == 'y' ]] || exit 1
fi
pct exec "$ctid" -- sh -c 'command -v apt-get >/dev/null && test -f /etc/debian_version' || { echo 'Requires Debian LXC'; exit 1; }
pct exec "$ctid" -- apt-get update
pct exec "$ctid" -- apt-get install -y python3 ca-certificates
pct exec "$ctid" -- mkdir -p /opt/proxmox-power-manager/web /etc/proxmox-power-manager /etc/proxmox-power-manager
for f in server.py auth.py index.html app.js; do pct push "$ctid" "$ROOT/web/$f" "/opt/proxmox-power-manager/web/$f"; done
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
echo 'Web UI installed. Access port 8080 on the LXC IP (LAN only).'
echo "Authentication settings: /etc/proxmox-power-manager/auth.json (inside CT $ctid)"
echo 'WARNING: Plain HTTP on port 8080. Restrict access to LAN; use HTTPS reverse proxy for remote access.'
echo 'WARNING: API token grants privileged power-manager settings access. Keep it secret; restrict TCP/8765 to the web LXC IP with a firewall.'
