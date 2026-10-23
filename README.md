# Proxmox Power Manager

> **Experimental software — not production-ready.** Do not enable unattended suspend on a Proxmox host with important workloads until you have tested battery-powered RTC wake, recovery, backups and host startup behavior. The default setting is `"enabled": false`.

Proxmox Power Manager is an open-source-oriented prototype for running Proxmox VE on a battery-powered laptop or another machine exposing Linux battery and AC power status. It monitors power, gracefully stops running LXC containers and QEMU virtual machines, suspends the host with an RTC alarm, and restores the previously running guests after AC power returns. An optional lightweight web dashboard runs in a separate Debian LXC container.

**Current development:** v0.6 installer work in `feature/installer-v0.6` (not released). The power-management core remains experimental.

## Quick start — install, update and remove

> Development branch: `feature/installer-v0.6`. Run these commands as `root` **on the Proxmox VE host**, not inside an LXC. Review the remote installer before executing it.

### Install with one command

```bash
curl -fsSL https://raw.githubusercontent.com/op1993/Proxmox-Power-Manager/feature/installer-v0.6/install.sh | PPM_REF=feature/installer-v0.6 bash
```

This downloads the selected branch and starts the **interactive** installer. Choose **1** for host agent only, **2** for agent + newly created Debian LXC dashboard (recommended for a dedicated PPM web container), or **3** for agent + an existing Debian LXC. For mode 2, select automatic defaults or advanced setup, review the proposed CTID/storage/network settings, and confirm creation. Keep the initial `admin` password displayed once during setup. The web dashboard is served on the LXC's port `8080` (HTTP; LAN only unless protected by an HTTPS reverse proxy). The host API uses port `8765`; restrict access to the PPM web LXC.

The installer is **not unattended**: the single command starts an interactive setup. On first install automatic suspend is disabled; test RTC wake and guest recovery before enabling it.

### Update with one command

```bash
ppm update
```

Run as root on the host. The installed `ppm` launcher uses `/etc/proxmox-power-manager/update-ref` (the installer sets `feature/installer-v0.6`). The updater checks tests, refuses to update when guest recovery is pending, backs up host files, updates the host agent and the running web LXC, and restarts services. **The web LXC must be running** for a web installation. Updates preserve installed configuration, credentials and recovery data.

Useful checks:

```bash
ppm status
ppm version
systemctl status proxmox-power-manager.service
```

### Choose an update branch (development vs. main)

`ppm update` reads the installed branch from `/etc/proxmox-power-manager/update-ref`. The file is created by the installer and normally points to `feature/installer-v0.6` for this development installation.

**Update from the feature branch** (keep testing unreleased changes):

```bash
printf '%s\\n' 'feature/installer-v0.6' > /etc/proxmox-power-manager/update-ref
ppm update
```

**Update from `main`** (after the required changes have been merged there):

```bash
printf '%s\\n' 'main' > /etc/proxmox-power-manager/update-ref
ppm update
```

Check the selected branch with `ppm version`. These commands must be run as root on the Proxmox host. Switching the update source is **not a downgrade mechanism**: before switching to `main`, confirm that `main` contains the version you want and that the updater supports your installed configuration. Back up settings and test updates before changing branches on a host managing power and guest recovery.

For a **fresh installation directly from main**, use:

```bash
curl -fsSL https://raw.githubusercontent.com/op1993/Proxmox-Power-Manager/main/install.sh | PPM_REF=main bash
```

Review the installer on `main` before running it. The command only works if that branch contains the corresponding bootstrap installer.

### Merge the feature branch into main

Use a GitHub Pull Request to review and merge the feature branch:

1. Push your local commits (if any): `git push origin feature/installer-v0.6`.
2. Open [GitHub Pull Requests](https://github.com/op1993/Proxmox-Power-Manager/pulls) → **New pull request**.
3. Set **base: `main`** and **compare: `feature/installer-v0.6`**. Review the diff, ensure CI/tests pass, and create the PR.
4. Merge the PR into `main` after review. Keep the feature branch until you have verified installation/update from `main`.
5. On the Proxmox host, switch the update source to `main` using the commands above.

Alternatively, if you manage the repository locally and have permission to push `main`:

```bash
git fetch origin
git switch main
git pull --ff-only origin main
git merge --no-ff origin/feature/installer-v0.6
git push origin main
```

Prefer the Pull Request route when branch protection or CI checks are configured. Merging code into `main` does **not** automatically update installed Proxmox hosts; run `ppm update` on each host after selecting the intended branch.

### Uninstall manually (no automatic removal)

**Deleting the PPM web LXC from the Proxmox GUI does not uninstall PPM from the host.** The lifecycle watcher only detects a missing installer-owned container; its `cleanup-ready` marker is informational. The experimental `cleanup_plan.py` and `cleanup-policy.json` do **not** implement automatic deletion, even if `automatic_cleanup` is set to `true`. Automatic removal was intentionally left unimplemented.

1. **Prepare:** connect the host to AC power; ensure all previously stopped guests have been restored and `/var/lib/proxmox-power-manager/state.json` does **not** exist. Back up any settings, credentials and logs you want to keep. Do not uninstall during a suspend/recovery cycle.
2. **Remove host services:** download and inspect the repository's `scripts/uninstall.sh`, then run it as root. It prompts for confirmation and refuses removal while recovery state exists.

   ```bash
   curl -fsSL https://raw.githubusercontent.com/op1993/Proxmox-Power-Manager/feature/installer-v0.6/scripts/uninstall.sh -o /root/ppm-uninstall.sh
   less /root/ppm-uninstall.sh
   bash /root/ppm-uninstall.sh
   ```

   This disables the PPM host agent, API and cleanup timer, removes their systemd unit files, and removes the installed agent/cleanup code. **It deliberately preserves** the web LXC, host configuration, credentials, recovery data and logs.
3. **Remove the web LXC if it was dedicated to PPM:** find its ID in `/etc/proxmox-power-manager/installation.json`. Verify that the CTID matches the intended container. In the Proxmox GUI, select that LXC and use **More → Remove/Destroy** after backing up any required data. This permanently deletes the container and its data; **never destroy an existing shared LXC** installed via mode 3 just to remove PPM.
4. **Review the host firewall:** the installer may have added an inbound TCP/8765 ACCEPT rule commented `PPM Web LXC <CTID>`. Inspect **Datacenter/Node → Firewall → Rules** (or `pvesh get /nodes/$(hostname -s)/firewall/rules --output-format json`) and remove **only** the exact PPM-owned rule. Do not remove unrelated rules.
5. **Optional final cleanup:** after confirming recovery is complete and keeping any backups you need, manually review `/etc/proxmox-power-manager/`, `/var/lib/proxmox-power-manager/`, `/opt/proxmox-power-manager/` and `/usr/local/bin/ppm` for remaining PPM-only files. The uninstall script does not delete these automatically. Do not remove shared directories or files whose ownership is uncertain.

For an **agent-only** installation, skip the web LXC and firewall steps. For a **user-provided existing LXC**, remove PPM web files and its `proxmox-power-manager-web.service` within that container only after verifying it does not host other workloads; do not destroy the container itself.

---


## OIDC / SSO authentication (experimental)

The web dashboard supports a generic OpenID Connect Authorization Code + PKCE
login using an HTTPS OIDC provider. This is not tied to Authentik. Supported
providers must publish standard OIDC discovery metadata, issue **RS256**
signed ID tokens, and accept a confidential client with a client secret.

**Prerequisites:** publish the web UI behind an HTTPS reverse proxy and set
`PPM_PUBLIC_URL=https://your-dashboard.example.com` in
`/etc/proxmox-power-manager/web.env` **inside the web LXC**. Set
`PPM_HTTPS=1` there too. Restart
`proxmox-power-manager-web.service` inside that LXC. The URL must be the
external HTTPS origin with no trailing slash or path. The callback to register
in your OIDC provider is
`https://your-dashboard.example.com/auth/oidc/callback`.

Open **Settings → Authorization (OIDC / SSO)** while logged in locally.
Enter the provider's exact Issuer URL, Client ID and Client Secret, and
optionally an allowlist of immutable OIDC `sub` values. **Without an
allowlist, every user authenticated by the configured OIDC provider can
access the dashboard as an administrator.** Prefer enforcing access via
provider-side application policy as well as setting the allowlist.
Save, sign out, and test the **Sign in with SSO** button.

To disable local password login, sign in using OIDC, return to Settings and
disable the local login checkbox within five minutes. This cannot be done
from a password-authenticated session. Existing local sessions are rejected
once local login is disabled. If OIDC becomes unavailable, restore local login
via the web LXC console by editing
`/etc/proxmox-power-manager/auth.json` to set
`"local_login_enabled": true` and restart the web service.

OIDC settings and client secret live in the web LXC's root-readable
`auth.json`, not in the Proxmox host's power configuration. The existing
`oidc.client_secret_env` placeholder from older installs is ignored by this
implementation. The web service requires the `openssl` executable for
RS256 verification. SSO does not implement periodic provider-side session
revocation checks; already-issued dashboard sessions last up to eight hours.

## How it works

```text
Browser ──HTTP :8080 (LAN only)──> Web UI (Debian LXC)
                                        │
                                HTTPS + bearer token
                                        │
                                        ▼
                           Host API (Proxmox :8765)
                                        │
                                 Limited operations
                                        │
                           Host power-manager agent
                           ├─ AC / battery via sysfs
                           ├─ pct / qm guest lifecycle
                           ├─ saved recovery state
                           └─ rtcwake / deep S3 sleep
```

The agent runs **on the Proxmox host**, not in the web LXC. The dashboard may go offline when the host suspends; the host agent resumes independently. The dashboard communicates with the host through a narrow HTTPS API rather than SSH. The API authenticates with a generated bearer token and the web client verifies the agent's TLS certificate.

### Power-management sequence

1. While AC power is available, the agent polls the battery and AC state at the configured interval. If a recovery record exists, it tries to restore recorded guests, subject to the minimum battery percentage.
2. When AC is lost, the agent leaves guests running until battery charge reaches `sleep_threshold` (default **30%**).
3. It saves the IDs of *currently running* LXC containers and, when enabled, QEMU VMs in an atomic recovery file **before** shutting them down.
4. It requests graceful shutdowns, checks whether guests stopped, and **aborts suspend** if any guests remain running (including unexpected guests).
5. If power is still absent, it selects an RTC wake interval: **15 minutes** normally, or **60 minutes** at or below `low_threshold` (default **15%**), then requests `deep` suspend with `rtcwake`.
6. After RTC wake, it checks AC again. If AC is still absent, it repeats the sleep cycle without restoring guests. If AC has returned and charge meets `minimum_restore_percent` (default **15%** in the example config), it starts the recorded guests.
7. The recovery file is deleted only after all recorded guests are verified running. Otherwise it is retained for another recovery attempt.
8. At or below `critical_threshold` (default **8%**), `critical_action` controls whether the agent requests host poweroff or logs a warning. **Poweroff may leave the machine offline indefinitely** if its firmware cannot boot automatically when AC returns.

This is the intended control flow implemented in the current code; it is **not a guarantee of safe operation** during every real power failure. For example, application-specific transactions and backup jobs are not detected, and interrupted recovery after an unexpected reboot is not fully handled.

## Features and current status

| Feature | Status |
| --- | --- |
| AC/battery monitoring from `/sys/class/power_supply` | Implemented; paths configurable |
| Configurable battery thresholds and RTC intervals | Implemented |
| Record, gracefully stop and restore LXC | Implemented; needs integration testing |
| Optional QEMU VM stop/restore | Implemented; guest shutdown depends on VM cooperation |
| Persistent recovery state | Implemented; boot-time recovery not fully solved |
| Web status/configuration/dry-run | Basic implementation |
| Local web username/password | Implemented; generated `admin` password |
| Google/Authentik/other OIDC | **Configuration placeholder only; not functional** |
| HTTPS host API + token + certificate verification | Implemented |
| New/existing Debian LXC installation | Interactive installer; not validated on real Proxmox |
| GitHub one-command bootstrap | Implemented in v0.6 development branch; not integration tested |
| Automatic LXC defaults / Debian template download | Implemented in v0.6 development branch; not integration tested |
| Automatic firewall configuration | **Not implemented** |
| Certificate rotation / renewal | **Not implemented** |
| Fully automatic rollback / web upgrade | **Not implemented** |

## Requirements

- Proxmox VE host with root shell access and `pct`, `qm`, `systemctl`, `python3` and `rtcwake`.
- Linux-visible AC and battery status (default paths below); supported suspend mode `deep`, plus functional RTC wake.
- For the web dashboard: Debian 12 or 13 LXC, network connectivity to the Proxmox host, `apt-get`, Python 3, and an available port 8080.
- For a **new** web LXC: a Debian 12/13 standard template already downloaded to Proxmox template storage; free CTID; appropriate storage and bridge; DHCP connectivity.
- `openssl` on the Proxmox host for HTTPS API certificate generation.

> The v0.6 installer can download a Debian template and suggest CTID/storage/bridge defaults for a new LXC. It **does not configure a firewall or set up HTTPS for the browser**. Review every prompt before proceeding. Back up the host and any existing container first.

## Installation

### One-command bootstrap (development branch, test systems only)

Run on the Proxmox host as root **after reviewing** [`install.sh`](install.sh). This is an experimental installer that downloads and executes code with root privileges. It is not yet a signed or checksum-pinned release.

```bash
curl -fsSL https://raw.githubusercontent.com/op1993/Proxmox-Power-Manager/feature/installer-v0.6/install.sh -o /root/ppm-bootstrap.sh
PPM_REF=feature/installer-v0.6 bash /root/ppm-bootstrap.sh
```

The bootstrap downloads the selected branch and invokes `scripts/install.sh`. Choose `2` for a new LXC, then choose automatic defaults (`1`) or advanced (`2`). The installer will ask for confirmation before creating a container. For public stable installation, wait for a tagged, verified release.

### Manual installation

Download or clone the project to a trusted location on the **Proxmox host**. From the project directory, run as root:

```bash
bash -n scripts/install.sh
bash scripts/install.sh
```

The installer offers:

1. **Agent only:** installs the host agent and systemd service, without the API or web dashboard.
2. **Agent + new LXC:** offers automatic defaults (unused CTID, active storage, vmbr0, cached/downloaded Debian template) or advanced settings (CTID, storage, bridge, cores, RAM, disk); creates an unprivileged Debian LXC (default 1 core, 256 MiB RAM, 256 MiB swap, 4 GiB root disk, DHCP), then installs the dashboard.
3. **Agent + existing Debian LXC:** asks for the host's LAN IPv4 address and a running Debian CTID, then installs the dashboard into it. **This modifies the existing container**; back it up first.

The agent's initial config is copied from `config/config.example.json` only if no installed config already exists. The installer enables/restarts the host service; for web modes it also provisions the HTTPS API and web service. It does **not** turn on automatic suspend.

For a new LXC, inspect downloaded templates first:

```bash
pveam list local
pveam update
pveam available --section system | grep -E 'debian-(12|13)'
# Download the desired template using its exact filename:
# pveam download local <template-filename>
```

The v0.6 installer selects a cached Debian 12/13 template, or downloads one if none is cached. The selected template storage must support `vztmpl` content.

After successful installation, find the container's IP:

```bash
pct exec <CTID> -- hostname -I
```

Open `http://<LXC-IP>:8080` **from your trusted LAN only**. The first web installation generates a random password for username `admin` and prints it **once** in the installer output. Save it in a password manager. On reinstall, existing credentials are preserved.

**Important:** the development-branch bootstrap above is not a production-ready, pinned release. Do not enable unattended suspend before completing real hardware tests.

## Command-line management (development branch)

On a new installation the installer registers `/usr/local/bin/ppm`. Existing installations can install it once:

```bash
curl -fsSL https://raw.githubusercontent.com/op1993/Proxmox-Power-Manager/feature/installer-v0.6/scripts/ppm -o /tmp/ppm-cli
install -m 0755 /tmp/ppm-cli /usr/local/bin/ppm
ppm version
```

Then run `ppm update` to fetch and run the branch updater, `ppm status` for host status, or `ppm version` to show the configured update ref. Updates require automatic sleep disabled and no pending recovery state. This development updater executes code fetched from GitHub as root; review before use.

## Configuration

Host agent config: `/etc/proxmox-power-manager/config.json` (example: [`config/config.example.json`](config/config.example.json)). The settings are JSON, not YAML.

| Key | Example | Meaning |
| --- | --- | --- |
| `enabled` | `false` | Enables automatic sleep; **off by default** |
| `sleep_threshold` | `30` | Battery % at which guest shutdown/sleep begins |
| `low_threshold` | `15` | Battery % for longer RTC wake interval |
| `critical_threshold` | `8` | Battery % for critical action |
| `normal_wake_minutes` | `15` | RTC wake interval above low threshold |
| `low_wake_minutes` | `60` | RTC wake interval at/below low threshold |
| `check_seconds` | `60` | Monitoring interval while awake |
| `shutdown_timeout` | `120` | Graceful guest shutdown timeout in seconds |
| `ac_path` | `/sys/class/power_supply/ADP0/online` | Host AC online status file |
| `battery_path` | `/sys/class/power_supply/BAT0/capacity` | Host battery capacity file |
| `manage_vms` | `true` | Also manage QEMU virtual machines |
| `minimum_restore_percent` | `15` | Minimum charge for restoration even after AC returns |
| `critical_action` | `poweroff` | `poweroff` or `warn`; **dangerous without verified auto-power-on** |

The threshold ordering must satisfy `critical_threshold < low_threshold < sleep_threshold`. The example has `critical_action: poweroff` but that action has no effect until `enabled` is explicitly set to `true`. Consider `warn` when auto-power-on from S5 is unavailable; this also carries the risk of the battery running out.

### Web authentication and future OIDC

The dashboard **requires a local username and password**. On first installation it generates a random `admin` password and stores only its salted `scrypt` hash. Authentication settings are stored **inside the LXC** at `/etc/proxmox-power-manager/auth.json` (permissions `0600`), not in the source repository. Session cookies are HttpOnly and SameSite=Strict, with CSRF protections and per-IP login throttling.

The `oidc` section in `auth.json` reserves `enabled`, `issuer_url`, `client_id` and `client_secret_env` for future Google, Authentik, Keycloak or other OIDC support. OIDC is now implemented through the web authorization settings; the legacy `client_secret_env` placeholder is ignored. Local login can be disabled only after a successful OIDC sign-in.

The web server listens on plain HTTP port 8080. Use a trusted LAN only or place it behind an HTTPS reverse proxy with appropriate network controls. `PPM_HTTPS=1` in the web service environment marks cookies `Secure` when served through HTTPS. A password does **not** encrypt plain HTTP traffic.

### Agent API and secrets

For web modes, the installer creates:

| Host path | Purpose |
| --- | --- |
| `/etc/proxmox-power-manager/api.env` | API bind address and port (8765) |
| `/etc/proxmox-power-manager/api-token` | Random bearer token |
| `/etc/proxmox-power-manager/api.crt` | Self-signed TLS certificate (365 days) |
| `/etc/proxmox-power-manager/api.key` | TLS private key |
| `/etc/proxmox-power-manager/web.env` | Web service environment copied into LXC |

The token and certificate are copied into the web LXC for API communication. The certificate includes the configured host IPv4 address as a subject alternative name; the web client verifies it. **The installer does not configure firewall rules. Restrict TCP/8765 on the Proxmox host to the web LXC's IP; never expose it to the Internet.** Rotate the certificate and token securely when necessary; automatic rotation is not yet implemented.

Supported API routes (all require a bearer token):

| Method | Route | Operation |
| --- | --- | --- |
| `GET` | `/v1/status` | Power status and guest state |
| `GET` | `/v1/config` | Read agent configuration |
| `POST` | `/v1/config` | Update allowed configuration fields |
| `POST` | `/v1/dry-run` | Evaluate policy without suspend |

There is no arbitrary command execution endpoint and no API route to immediately suspend the host.

## Operations and diagnostics

Run on the Proxmox host:

```bash
python3 /opt/proxmox-power-manager/agent/power_manager.py status
python3 /opt/proxmox-power-manager/agent/power_manager.py dry-run
systemctl status proxmox-power-manager
journalctl -u proxmox-power-manager -f
systemctl status proxmox-power-manager-api
journalctl -u proxmox-power-manager-api -n 100 --no-pager
```

Inside the web LXC:

```bash
systemctl status proxmox-power-manager-web
journalctl -u proxmox-power-manager-web -n 100 --no-pager
```

`dry-run` does not stop guests or suspend the host. The command `once` executes one real policy cycle and **may stop guests/suspend the host if enabled**; do not use it as a harmless test. The `restore` command attempts to restart recorded guests when AC and minimum battery conditions are satisfied.

Recovery state: `/var/lib/proxmox-power-manager/state.json`. **Do not delete it while recovery is pending**; it identifies guests that must be restarted.

## Updating and uninstalling

From a trusted source checkout on the Proxmox host:

```bash
# First disable automatic sleep and ensure recovery is complete.
bash scripts/update.sh
```

The update script runs Python checks and unit tests, backs up the host agent/configuration, and updates the **host agent**. It does **not** automatically update the web LXC, and rollback is manual. Do not run it while `state.json` indicates pending recovery. Back up both host and LXC before upgrading. Upgrading an existing SSH-based v0.4 installation to the HTTPS API architecture is **not an automatic migration**: old SSH keys must be removed manually after verifying the new transport.

```bash
bash scripts/uninstall.sh
```

The uninstall script asks for confirmation, stops/disables the host agent and API services, and removes host agent files. **It leaves web LXC, credentials, certificates, configuration, recovery data and logs** for manual review. It refuses to run while recovery state exists.

## Safety and limitations

- **No real Proxmox integration validation** of this installer and current codebase is claimed. Unit tests do not replace blackout tests.
- RTC wake after S3 was previously observed on a Lenovo laptop **while AC was connected**, but battery-only wake has not been verified. S5 automatic power-on has not been verified.
- Guest shutdown is graceful only to the extent guests cooperate. In-flight backups, databases and application transactions are not coordinated.
- Unexpected reboot, Proxmox guest `onboot` interactions, and recovery after partially completed shutdown need more work.
- New/existing LXC installation has no transactional rollback; partial failure may leave installed services or a partially configured container.
- The dashboard itself is shut down with other LXC guests during suspend and will be unreachable while asleep.
- Port 8080 is HTTP-only and port 8765 is a privileged host API. Network restrictions are the operator's responsibility.
- Certificates expire after 365 days. There is no automatic renewal, firewall setup, full web upgrade, or comprehensive audit log yet. The v0.6 remote bootstrap is experimental and lacks signed release verification.
- Do not publish runtime configs, tokens, `auth.json`, `.env` files, TLS keys or backups. `.gitignore` reduces accidental commits but does not remove already-tracked secrets.

## Development

```bash
python3 -m unittest discover -s tests -v
bash -n scripts/install.sh scripts/update.sh scripts/uninstall.sh
```

The project has a GitHub Actions workflow in `.github/workflows/check.yml`. Project repository: https://github.com/op1993/Proxmox-Power-Manager. Review changes and CI results before merging.

## Project structure

```text
agent/              Host monitoring, recovery logic, and HTTPS API
web/                Dashboard, login and HTTP server
config/             Public example configuration
systemd/            Host and LXC systemd units
scripts/            Interactive installer, update, uninstall
tests/              Python unit tests
.github/workflows/  CI checks
.gitignore          Excludes local secrets and generated files
README.md           This documentation
```

## v0.6 development notes

The host agent deliberately owns suspend, RTC wake, guest shutdown and recovery. The LXC is the web control plane only. This prevents the control-plane container from stopping itself in the middle of host power management.

The installer verifies that the LXC can authenticate to the host HTTPS API, but it **does not automatically configure Proxmox firewall rules**. Restrict port 8765 to the web container. New installations keep `enabled=false`; do not enable unattended suspend until AC-loss, RTC wake and recovery are tested on the target hardware.

`scripts/update.sh` updates the host agent only. It backs up host agent files and systemd units, and attempts to roll back on an update error. Web UI upgrades, full transactional rollback and cold-boot guest gating are not implemented yet. In particular, normal Proxmox `onboot` guests may start after a cold boot regardless of battery state; do not rely on this project to prevent that until cold-boot gating has been designed and tested.

## LXC lifecycle cleanup status

Automatic uninstall after deleting the web LXC is **not implemented**. The observer (`scripts/cleanup_watch.py`) can mark confirmed absence of an installer-created container after repeated cluster checks; it does not remove host components. The read-only `scripts/cleanup_plan.py` may display eligibility, but neither it nor the `automatic_cleanup` policy performs deletion. Use the **manual uninstall** procedure in Quick start above. Do not assume that deleting the LXC disables the host power-management agent.

