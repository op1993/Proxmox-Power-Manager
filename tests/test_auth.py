import importlib.util
import pathlib
import time
import unittest

SPEC = importlib.util.spec_from_file_location('auth', pathlib.Path(__file__).resolve().parents[1] / 'web' / 'auth.py')
auth = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auth)

class TestAuth(unittest.TestCase):
    def test_hash_and_verify(self):
        hashed = auth.password_hash('secure random password')
        self.assertTrue(auth.verify_password('secure random password', hashed))
        self.assertFalse(auth.verify_password('wrong', hashed))
        self.assertNotIn('secure random password', hashed)
    def test_session(self):
        config = {'session_secret': '11' * 32}
        cookie, csrf = auth.sign_session(config)
        self.assertEqual(auth.verify_session(cookie, config), csrf)
        self.assertIsNone(auth.verify_session(cookie + 'x', config))
        self.assertIsNone(auth.verify_session(cookie, {'session_secret': '22' * 32}))
