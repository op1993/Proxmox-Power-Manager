"""OIDC configuration validation and provider discovery.

This module does not authenticate users. Local login must remain enabled until
the complete authorization-code flow and token verification are implemented.
"""
import ipaddress
import json
import socket
import urllib.parse
import urllib.request

MAX_RESPONSE = 65536

def validate_issuer(issuer):
    if not isinstance(issuer, str) or not issuer or len(issuer) > 2048:
        raise ValueError('Invalid OIDC issuer')
    parsed = urllib.parse.urlsplit(issuer)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('OIDC issuer must be a clean HTTPS URL')
    if parsed.port not in (None, 443):
        raise ValueError('Nonstandard OIDC issuer port is not supported')
    for answer in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM):
        addr = ipaddress.ip_address(answer[4][0])
        if not addr.is_global:
            raise ValueError('OIDC issuer must resolve to a public address')
    return issuer.rstrip('/')

def discover(issuer):
    """Discovery for public HTTPS issuers only; never follow redirects."""
    issuer = validate_issuer(issuer)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ValueError('OIDC discovery redirects are disabled')
    url = issuer + '/.well-known/openid-configuration'
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(urllib.request.Request(url, headers={'Accept':'application/json'}), timeout=5) as response:
        if response.status != 200 or int(response.headers.get('Content-Length', '0')) > MAX_RESPONSE:
            raise ValueError('Invalid OIDC discovery response')
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError('OIDC discovery response too large')
    data = json.loads(raw)
    if data.get('issuer') != issuer:
        raise ValueError('OIDC issuer mismatch')
    for key in ('authorization_endpoint', 'token_endpoint', 'jwks_uri'):
        endpoint = data.get(key, '')
        if not isinstance(endpoint, str) or not endpoint.startswith('https://'):
            raise ValueError('Invalid OIDC ' + key)
    return data
