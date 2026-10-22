#!/usr/bin/env bash
# Executed inside the existing Debian web LXC, not on the Proxmox host.
set -euo pipefail
WEB=/opt/proxmox-power-manager/web
test -f "$WEB/package.json" || { echo "Router package.json missing" >&2; exit 1; }
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  apt-get update
  apt-get install -y nodejs npm
fi
node -e 'if (Number(process.versions.node.split(".")[0]) < 18) process.exit(1)' || {
  echo 'Node.js 18+ required for Playwright; upgrade Node.js in LXC' >&2
  exit 1
}
cd "$WEB"
npm install --omit=dev --no-audit --no-fund
npx playwright install --with-deps chromium
echo 'Playwright and Chromium installed in web LXC.'
