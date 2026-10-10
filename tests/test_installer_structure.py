from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = (ROOT / "scripts/install.sh").read_text()


class InstallerStructureTests(unittest.TestCase):
    def test_managed_container_created_before_host_agent(self):
        create = INSTALLER.index('  pct create "$ctid"')
        manifest = INSTALLER.index("  PPM_CTID=\"$ctid\" python3 - <<'PYMANIFEST'")
        host = INSTALLER.index("  install_host_agent", create)
        self.assertLess(create, manifest)
        self.assertLess(manifest, host)

    def test_timer_enabled_only_after_api_verification(self):
        check = INSTALLER.index("echo 'Testing API connectivity from the container...'")
        enable = INSTALLER.index("  systemctl enable --now proxmox-power-manager-cleanup.timer")
        self.assertLess(check, enable)
        self.assertIn("  exit 1\nfi\nif [[ \"$mode\" == 2 ]]; then", INSTALLER)

    def test_partial_installation_preserves_container(self):
        self.assertIn("trap on_managed_install_exit EXIT", INSTALLER)
        self.assertIn("'installation_complete': False", INSTALLER)
        self.assertIn("data['installation_complete'] = True", INSTALLER)
        self.assertNotIn('pct destroy "$ctid"', INSTALLER)

    def test_manifest_has_valid_newline_expression(self):
        self.assertIn("p.write_text(json.dumps(data, indent=2) + '\\n')", INSTALLER)
        self.assertNotIn("p.write_text(json.dumps(data, indent=2) + '\\\\n')", INSTALLER)


if __name__ == "__main__":
    unittest.main()
