#!/usr/bin/env python3
"""Minimal TLS control API. Never executes caller-provided commands."""
import hmac
import json
import os
import pathlib
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from control import execute

TOKEN_FILE = pathlib.Path('/etc/proxmox-power-manager/api-token')
MAX_BODY = 4096

class Handler(BaseHTTPRequestHandler):
    def respond(self, status, value):
        data = json.dumps(value).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        provided = self.headers.get('Authorization', '')
        expected = 'Bearer ' + TOKEN_FILE.read_text().strip()
        return hmac.compare_digest(provided, expected)

    def handle_api(self, method):
        if not self.authorized():
            return self.respond(401, {'error': 'Unauthorized'})
        routes = {('GET', '/v1/status'): 'status', ('GET', '/v1/config'): 'config',
                  ('GET', '/v1/history'): 'history', ('POST', '/v1/history/date'): 'history-date', ('GET', '/v1/router/history'): 'router-history', ('GET', '/v1/telegram/config'): 'telegram-config', ('POST', '/v1/telegram/config'): 'telegram-update', ('POST', '/v1/telegram/test'): 'telegram-test', ('GET', '/v1/hdd/disks'): 'hdd-list', ('POST', '/v1/config'): 'update', ('POST', '/v1/dry-run'): 'dry-run', ('POST', '/v1/hdd/start'): 'hdd-start'}
        action = routes.get((method, self.path))
        if not action:
            return self.respond(404, {'error': 'Not found'})
        try:
            payload = None
            if method == 'POST':
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 <= length <= MAX_BODY:
                    return self.respond(413, {'error': 'Payload too large'})
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    return self.respond(400, {'error': 'Expected object'})
            result = execute(action, payload)
            return self.respond(200, result)
        except (ValueError, json.JSONDecodeError) as exc:
            return self.respond(400, {'error': str(exc)})
        except Exception:
            return self.respond(500, {'error': 'Agent error'})

    def do_GET(self):
        self.handle_api('GET')

    def do_POST(self):
        self.handle_api('POST')

    def log_message(self, fmt, *args):
        pass  # Never log credentials or bearer tokens.

class Server(ThreadingHTTPServer):
    daemon_threads = True

if __name__ == '__main__':
    host = os.environ['PPM_API_BIND']
    port = int(os.environ.get('PPM_API_PORT', '8765'))
    server = Server((host, port), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain('/etc/proxmox-power-manager/api.crt', '/etc/proxmox-power-manager/api.key')
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    server.serve_forever()
