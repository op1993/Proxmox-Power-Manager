import importlib.util
import pathlib
import unittest
from unittest.mock import patch
ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('control', ROOT/'agent/control.py')
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)
class ApiControlTest(unittest.TestCase):
    def test_reject_unknown_action(self):
        with self.assertRaises(ValueError): control.execute('shell')
    def test_reject_unsafe_configuration(self):
        cfg = {'enabled': False, 'critical_threshold': 8, 'low_threshold': 15, 'sleep_threshold': 30, 'normal_wake_minutes': 15, 'low_wake_minutes': 60, 'check_seconds': 60, 'shutdown_timeout': 120}
        with self.assertRaises(ValueError): control.validate(cfg, {'ac_path': '/tmp/evil'})
if __name__ == '__main__': unittest.main()
