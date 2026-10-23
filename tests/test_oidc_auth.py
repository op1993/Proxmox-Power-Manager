"""Offline OIDC smoke tests. Run: python3 -m unittest discover -s tests"""
import base64
import hashlib
import hmac
import importlib.util
import json
import pathlib
import sys
import unittest
from unittest.mock import patch

WEB=pathlib.Path(__file__).resolve().parents[1]/'web'
sys.path.insert(0,str(WEB))
import oidc
import auth

class OIDCTests(unittest.TestCase):
    def test_state_roundtrip_and_tamper(self):
        secret='ab'*32
        state=oidc.pack({'state':'test','issued':123},secret)
        self.assertEqual(oidc.unpack(state,secret)['state'],'test')
        with self.assertRaises(ValueError):
            oidc.unpack(state[:-1] + ('x' if state[-1]!='x' else 'y'),secret)

    def test_session_method_bound(self):
        cfg={'session_secret':'cd'*32,'local_login_enabled':True,'oidc':{'enabled':True}}
        cookie,nonce=auth.sign_session(cfg,'oidc')
        self.assertEqual(auth.verify_session(cookie,cfg),nonce)
        self.assertIsNone(auth.verify_session(cookie.replace('.oidc.','.local.'),cfg))
        cfg['oidc']['enabled']=False
        self.assertIsNone(auth.verify_session(cookie,cfg))

    def test_disable_local_revokes_password_sessions(self):
        cfg={'session_secret':'ef'*32,'local_login_enabled':True,'oidc':{'enabled':True}}
        cookie,_=auth.sign_session(cfg,'local')
        cfg['local_login_enabled']=False
        self.assertIsNone(auth.verify_session(cookie,cfg))

if __name__=='__main__':
    unittest.main()
