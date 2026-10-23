#!/usr/bin/env bash
# Proxmox Power Manager remote updater.
# Review this script before running it as root.
set -Eeuo pipefail
umask 077

REPO="op1993/Proxmox-Power-Manager"
REF="${PPM_REF:-main}"

if [[ ${EUID} -ne 0 ]]; then
  echo "ERROR: Run as root on the Proxmox host." >&2
  exit 1
fi
for cmd in curl tar mktemp bash pct python3; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "ERROR: Missing prerequisite: $cmd" >&2
    exit 1
  }
done
if [[ ! -r /etc/pve/.version ]]; then
  echo "ERROR: This does not appear to be a Proxmox VE host." >&2
  exit 1
fi
if [[ ! "$REF" =~ ^[A-Za-z0-9._/-]+$ || "$REF" == *..* || "$REF" == /* ]]; then
  echo "ERROR: Invalid PPM_REF." >&2
  exit 1
fi

tmp="$(mktemp -d /tmp/ppm-installer.XXXXXXXX)"
trap 'rm -rf -- "$tmp"' EXIT
archive="$tmp/source.tar.gz"
url="https://github.com/$REPO/archive/$REF.tar.gz"
echo "Downloading $REPO at ref $REF"
curl --fail --location --show-error --silent \
  --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 180 \
  --output "$archive" "$url"
[[ -s "$archive" ]] || { echo "ERROR: Empty download." >&2; exit 1; }

# Reject paths that could escape the extraction directory and archive links.
python3 - "$archive" <<'PY'
import sys, tarfile
with tarfile.open(sys.argv[1], "r:gz") as tar:
    members = tar.getmembers()
    if len(members) > 2000:
        raise SystemExit("ERROR: Archive contains too many files")
    for member in members:
        parts = member.name.split("/")
        if (member.name.startswith("/") or ".." in parts or
                not (member.isfile() or member.isdir())):
            raise SystemExit("ERROR: Unsafe archive entry")
PY
mkdir -p "$tmp/src"
tar -xzf "$archive" -C "$tmp/src" --no-same-owner --no-same-permissions
mapfile -t installers < <(find "$tmp/src" -mindepth 3 -maxdepth 3 -type f -path '*/scripts/install.sh')
if [[ ${#installers[@]} -ne 1 ]]; then
  echo "ERROR: Expected exactly one scripts/install.sh." >&2
  exit 1
fi
echo "Source downloaded. Running updater."
bash "$(dirname "${installers[0]}")/update.sh"
