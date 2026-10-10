import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cleanup_watch", ROOT / "scripts/cleanup_watch.py")
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


class CleanupWatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.manifest = d / "installation.json"
        self.recovery = d / "state.json"
        self.counter = d / "missing-count"
        self.ready = d / "cleanup-ready"
        self.config = d / "101.conf"
        p = patch.object(watch, "LXC_CONFIG_DIR", d)
        p.start()
        self.addCleanup(p.stop)
        self.manifest.write_text(json.dumps({
            "schema": 1, "web_ctid": 101, "web_ct_created_by_ppm": True
        }))
        for name, value in [
            ("MANIFEST", self.manifest), ("RECOVERY", self.recovery),
            ("COUNTER", self.counter), ("READY", self.ready),
        ]:
            p = patch.object(watch, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_no_manifest(self):
        self.manifest.unlink()
        self.assertEqual(watch.inspect(), "unregistered")

    def test_existing_container_is_not_owned(self):
        self.manifest.write_text(json.dumps({
            "schema": 1, "web_ctid": 101, "web_ct_created_by_ppm": False
        }))
        self.assertEqual(watch.inspect(), "external-container")

    def test_recovery_blocks_detection(self):
        self.recovery.write_text("{}")
        self.assertEqual(watch.inspect(), "recovery-pending")
        self.assertFalse(self.ready.exists())

    def test_cluster_outage_does_not_count(self):
        with patch.object(watch, "cluster_healthy", return_value=False):
            self.assertEqual(watch.inspect(), "cluster-unavailable")
        self.assertFalse(self.counter.exists())

    def test_three_missing_checks_only_mark_ready(self):
        with patch.object(watch, "cluster_healthy", return_value=True):
            self.assertEqual(watch.inspect(), "missing-unconfirmed")
            self.assertEqual(watch.inspect(), "missing-unconfirmed")
            self.assertEqual(watch.inspect(), "cleanup-ready")
        self.assertEqual(self.ready.read_text().strip(), "101")

    def test_reappearance_resets_confirmation(self):
        with patch.object(watch, "cluster_healthy", return_value=True):
            self.assertEqual(watch.inspect(), "missing-unconfirmed")
            self.config.write_text("hostname: ppm-web\\n")
            self.assertEqual(watch.inspect(), "present")
        self.assertFalse(self.counter.exists())
        self.assertFalse(self.ready.exists())

    def test_invalid_manifest_is_rejected(self):
        self.manifest.write_text(json.dumps({
            "schema": 1, "web_ctid": "101", "web_ct_created_by_ppm": True
        }))
        self.assertEqual(watch.inspect(), "invalid-manifest")


if __name__ == "__main__":
    unittest.main()
