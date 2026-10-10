import importlib.util
import pathlib
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('control',ROOT/'agent/control.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.cfg={'enabled':False,'sleep_threshold':30,'low_threshold':15,'critical_threshold':8,
                  'normal_wake_minutes':15,'low_wake_minutes':60,'check_seconds':60,'shutdown_timeout':120}
    def test_valid_update(self):
        self.assertEqual(mod.validate(self.cfg,{'low_wake_minutes':90})['low_wake_minutes'],90)
    def test_bad_thresholds(self):
        with self.assertRaises(ValueError): mod.validate(self.cfg,{'low_threshold':35})
    def test_bad_type(self):
        with self.assertRaises(ValueError): mod.validate(self.cfg,{'enabled':'true'})
    def test_unknown_key(self):
        with self.assertRaises(ValueError): mod.validate(self.cfg,{'ac_path':'/tmp/fake'})

if __name__=='__main__': unittest.main()
