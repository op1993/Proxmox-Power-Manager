#!/usr/bin/env bash
# Executed inside the existing Debian web LXC, not on the Proxmox host.
set -euo pipefail
WEB=/opt/proxmox-power-manager/web
started_at=$SECONDS
stage() { printf '\n[%s] [Router dependencies] %s (elapsed %ss)\n' "$(date '+%H:%M:%S')" "$*" "$((SECONDS-started_at))"; }
stage "Checking Node.js and npm"
test -f "$WEB/package.json" || { echo "Router package.json missing" >&2; exit 1; }
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  stage "Updating apt package lists"
  apt-get update
  stage "Installing Node.js and npm"
  apt-get install -y nodejs npm
fi
stage "Node version: $(node --version); npm version: $(npm --version)"
node -e 'if (Number(process.versions.node.split(".")[0]) < 18) process.exit(1)' || {
  echo 'Node.js 18+ required for Playwright; upgrade Node.js in LXC' >&2
  exit 1
}
cd "$WEB"
stage "Installing npm dependencies"
npm install --omit=dev --no-audit --no-fund
stage "Installing Chromium and Linux browser dependencies (download may take several minutes)"
npx playwright install --with-deps chromium
stage "Playwright and Chromium installed successfully"
