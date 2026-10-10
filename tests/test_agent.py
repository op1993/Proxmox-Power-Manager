import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ppm',ROOT/'agent/power_manager.py')
ppm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ppm)

class AgentTests(unittest.TestCase):
    def test_defaults_disabled(self):
        self.assertFalse(ppm.validate({})['enabled'])
    def test_threshold_order(self):
        with self.assertRaises(ValueError): ppm.validate({'low_threshold':35})
    def test_invalid_action(self):
        with self.assertRaises(ValueError): ppm.validate({'critical_action':'rm -rf /'})
    def test_atomic_state(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'state.json'
            ppm.atomic_json(p,{'containers':[101],'vms':[201]})
            self.assertEqual(p.stat().st_mode & 0o777,0o600)
    def test_ac_return_restores(self):
        cfg=ppm.validate({})
        with patch.object(ppm,'status',return_value={'ac_online':True,'battery_percent':50,'enabled':True,'saved_state':None}), patch.object(ppm,'restore_guests') as restore:
            ppm.cycle(cfg)
            restore.assert_called_once()
    def test_dry_run_never_suspends(self):
        cfg=ppm.validate({'enabled':True})
        with patch.object(ppm,'status',return_value={'ac_online':False,'battery_percent':20,'enabled':True,'saved_state':None}),patch.object(ppm,'stop_guests') as stop:
            ppm.cycle(cfg,dry_run=True)
            stop.assert_not_called()

if __name__=='__main__': unittest.main()
