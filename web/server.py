#!/usr/bin/env python3
"""Password-protected web UI; restricted SSH commands to the Proxmox host."""
from collections import defaultdict
import http.cookies
import json
import os
import pathlib
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import ssl
from urllib.error import HTTPError
from auth import load_auth, sign_session, verify_password, verify_session

ROOT = pathlib.Path(__file__).resolve().parent
API_URL = os.environ.get('PPM_API_URL', 'https://127.0.0.1:8765')
API_TOKEN_FILE = os.environ.get('PPM_API_TOKEN_FILE', '/etc/proxmox-power-manager/api-token')
API_CA = os.environ.get('PPM_API_CA', '/etc/proxmox-power-manager/api.crt')
PORT = int(os.environ.get('PPM_PORT', '8080'))
SECURE_COOKIE = os.environ.get('PPM_HTTPS', '0') == '1'
ATTEMPTS = defaultdict(list)
ATTEMPT_LOCK = threading.Lock()

def call(command, payload=None):
    routes = {'status': ('GET', '/v1/status'), 'config': ('GET', '/v1/config'),
              'update': ('POST', '/v1/config'), 'dry-run': ('POST', '/v1/dry-run'), 'history': ('GET', '/v1/history'), 'hdd-start': ('POST', '/v1/hdd/start'), 'hdd-list': ('GET', '/v1/hdd/disks')}
    method, path = routes[command]
    token = pathlib.Path(API_TOKEN_FILE).read_text().strip()
    data = json.dumps(payload if payload is not None else {}).encode() if method == 'POST' else None
    req = Request(API_URL + path, data=data, method=method,
                  headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    ctx = ssl.create_default_context(cafile=API_CA)
    with urlopen(req, context=ctx, timeout=35) as response:
        return json.load(response)

class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, obj, cookie=None):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; frame-ancestors 'none'")
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def session_nonce(self):
        try:
            cookies = http.cookies.SimpleCookie()
            cookies.load(self.headers.get('Cookie', ''))
            value = cookies['ppm_session'].value
            return verify_session(value, load_auth())
        except (KeyError, ValueError, OSError):
            return None

    def valid_origin(self):
        origin = self.headers.get('Origin')
        if not origin:
            return False
        parsed = urlsplit(origin)
        return parsed.scheme in ('http', 'https') and parsed.netloc == self.headers.get('Host') and parsed.path == ''

    def do_GET(self):
        if self.path in ('/', '/app.js'):
            filename = 'index.html' if self.path == '/' else 'app.js'
            data = (ROOT / filename).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8' if filename.endswith('html') else 'text/javascript; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)
            return
        nonce = self.session_nonce()
        if self.path == '/api/session':
            return self.send_json(200, {'authenticated': bool(nonce), 'csrf': nonce if nonce else None})
        if not nonce:
            return self.send_json(401, {'error': 'Authentication required'})
        try:
            if self.path == '/api/status':
                return self.send_json(200, call('status'))
            if self.path == '/api/history':
                return self.send_json(200, call('history'))
            if self.path == '/api/hdd/disks':
                return self.send_json(200, call('hdd-list'))
            if self.path == '/api/config':
                return self.send_json(200, call('config'))
            return self.send_json(404, {'error': 'Not found'})
        except HTTPError as exc:
            try:
                message = json.loads(exc.read().decode('utf-8')).get('error', 'Agent rejected request')
            except (ValueError, UnicodeDecodeError):
                message = 'Agent rejected request'
            return self.send_json(exc.code if 400 <= exc.code < 500 else 502, {'error': message if exc.code < 500 else 'Agent unavailable'})
        except Exception:
            return self.send_json(502, {'error': 'Agent unavailable'})

    def do_POST(self):
        if not self.valid_origin():
            return self.send_json(403, {'error': 'Origin required'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > 4096:
                return self.send_json(413, {'error': 'Invalid payload size'})
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError('Invalid JSON object')
        except (ValueError, UnicodeDecodeError):
            return self.send_json(400, {'error': 'Invalid request'})
        if self.path == '/api/login':
            ip = self.client_address[0]
            now = time.monotonic()
            with ATTEMPT_LOCK:
                recent = [t for t in ATTEMPTS[ip] if now - t < 300]
                if len(recent) >= 5:
                    return self.send_json(429, {'error': 'Too many attempts; retry in 5 minutes'})
                ATTEMPTS[ip] = recent
            try:
                config = load_auth()
                user = payload.get('username', '')
                password = payload.get('password', '')
                if not isinstance(user, str) or not isinstance(password, str):
                    raise ValueError('Invalid credentials')
                valid = secrets.compare_digest(user, config['username']) & verify_password(password, config['password_hash'])
                if not valid:
                    with ATTEMPT_LOCK:
                        ATTEMPTS[ip].append(now)
                    return self.send_json(401, {'error': 'Invalid username or password'})
                with ATTEMPT_LOCK:
                    ATTEMPTS.pop(ip, None)
                session, nonce = sign_session(config)
                cookie = f'ppm_session={session}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800'
                if SECURE_COOKIE:
                    cookie += '; Secure'
                return self.send_json(200, {'authenticated': True, 'csrf': nonce}, cookie)
            except (ValueError, OSError):
                return self.send_json(503, {'error': 'Authentication unavailable'})
        nonce = self.session_nonce()
        if not nonce or not secrets.compare_digest(self.headers.get('X-CSRF-Token', ''), nonce):
            return self.send_json(403, {'error': 'Authentication or CSRF check failed'})
        if self.path == '/api/logout':
            cookie = 'ppm_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'
            if SECURE_COOKIE:
                cookie += '; Secure'
            return self.send_json(200, {'ok': True}, cookie)
        try:
            if self.path == '/api/config':
                return self.send_json(200, call('update', payload))
            if self.path == '/api/hdd/start':
                return self.send_json(200, call('hdd-start', payload))
            if self.path == '/api/dry-run':
                return self.send_json(200, call('dry-run', payload))
            return self.send_json(404, {'error': 'Not found'})
        except Exception:
            return self.send_json(502, {'error': 'Agent unavailable'})

if __name__ == '__main__':
    load_auth()
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
