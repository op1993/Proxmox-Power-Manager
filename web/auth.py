"""Local password authentication; stdlib only. Config is root-readable JSON."""
import base64
import hashlib
import hmac
import json
import os
import pathlib
import secrets
import time

AUTH_PATH = pathlib.Path(os.environ.get('PPM_AUTH_CONFIG', '/etc/proxmox-power-manager/auth.json'))
SESSION_SECONDS = 8 * 3600

def password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f'scrypt:16384:8:1:{salt.hex()}:{key.hex()}'

def verify_password(password, encoded):
    try:
        algorithm, n, r, p, salt, expected = encoded.split(':')
        if algorithm != 'scrypt' or (int(n), int(r), int(p)) != (16384, 8, 1):
            return False
        actual = hashlib.scrypt(password.encode('utf-8'), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False

def load_auth():
    data = json.loads(AUTH_PATH.read_text())
    if not data.get('username') or not data.get('password_hash') or not data.get('session_secret'):
        raise ValueError('Incomplete auth config')
    return data

def sign_session(config):
    expires = str(int(time.time()) + SESSION_SECONDS)
    nonce = secrets.token_urlsafe(24)
    payload = f'{expires}.{nonce}'
    signature = hmac.new(bytes.fromhex(config['session_secret']), payload.encode(), hashlib.sha256).hexdigest()
    return f'{payload}.{signature}', nonce

def verify_session(cookie, config):
    try:
        expires, nonce, signature = cookie.split('.')
        if int(expires) < time.time() or int(expires) > time.time() + SESSION_SECONDS + 60:
            return None
        expected = hmac.new(bytes.fromhex(config['session_secret']), f'{expires}.{nonce}'.encode(), hashlib.sha256).hexdigest()
        return nonce if hmac.compare_digest(expected, signature) else None
    except (ValueError, AttributeError):
        return None
