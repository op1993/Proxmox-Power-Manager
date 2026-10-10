# Proxmox Power Manager

> **Experimental software — not production-ready.** Do not enable unattended suspend on a Proxmox host with important workloads until you have tested battery-powered RTC wake, recovery, backups and host startup behavior. The default setting is `"enabled": false`.

Proxmox Power Manager is an open-source-oriented prototype for running Proxmox VE on a battery-powered laptop or another machine exposing Linux battery and AC power status. It monitors power, gracefully stops running LXC containers and QEMU virtual machines, suspends the host with an RTC alarm, and restores the previously running guests after AC power returns. An optional lightweight web dashboard runs in a separate Debian LXC container.

**Current development:** v0.6 installer work in `feature/installer-v0.6` (not released). The power-management core remains experimental.

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

The `oidc` section in `auth.json` reserves `enabled`, `issuer_url`, `client_id` and `client_secret_env` for future Google, Authentik, Keycloak or other OIDC support. **OIDC login is not implemented; changing these fields does not enable it.** Local login cannot be disabled in this version.

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

## LXC lifecycle cleanup (work in progress)

The installer now writes `/etc/proxmox-power-manager/installation.json` after creating a new managed web LXC. The file records the CTID and an ownership flag. Existing user-supplied containers are never marked as owned. The `scripts/cleanup_watch.py` observer reports `present`, `missing-unconfirmed`, `recovery-pending`, `unregistered` or `invalid-manifest` without deleting anything. **Automatic cleanup after Proxmox UI Destroy is not enabled yet.** A missing config alone is insufficient proof of deliberate deletion; the planned systemd timer must check cluster health, repeat observations and preserve recovery state before any cleanup action. Do not manually destroy the web LXC expecting host services to be removed automatically.

### Confirmed LXC absence and host shutdown (experimental)

The lifecycle observer now checks cluster quorum and requires three consecutive missing checks before writing `/var/lib/proxmox-power-manager/cleanup-ready`. `scripts/cleanup_host.sh` is a separate, manual, guarded action that disables the power manager host services but deliberately preserves all secrets and data. **The timer does not invoke this script yet**, and the script is not installed by the installer. This is not an automatic uninstall implementation. Do not rely on it for cleanup following a GUI Destroy operation.

### Installation safety guard

For newly created web containers, the installer registers `installation_complete: false` first and changes it to `true` only after the web service starts and API connectivity has been checked. The cleanup observer ignores incomplete installations, and the timer is enabled only at the end of the new-LXC installation path. If installation fails, inspect and resolve the partial installation manually; the installer does not yet roll back created containers. Automatic cleanup is still disabled and requires a separate safety review.

### Managed LXC lifecycle and removal limitations

In the new-container installation mode, the LXC is created first, then its CTID is recorded in the host installation manifest, and only then are host services installed. The watcher starts only after successful web installation and API verification. It requires three consecutive healthy observations of the CT being absent from both local and cluster inventory; migration and outages must not count as removal. Stale removal markers are cleared when the installation manifest is invalid or ownership is revoked.

**Important:** the watcher currently creates a `cleanup-ready` marker only. It does **not** automatically disable or uninstall host services, remove secrets, or destroy containers. A guarded manual host cleanup script is provided for review, but is not wired into systemd. Do not interpret deletion of a web LXC as full uninstallation yet.
