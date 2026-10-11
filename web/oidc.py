"""OIDC authorization code + PKCE and RS256 ID token validation (stdlib + openssl)."""
import base64, hashlib, hmac, ipaddress, json, os, secrets, socket, subprocess, tempfile, time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from pathlib import Path

def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()
def unb64(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
def public_url(value):
    u=urlsplit(value)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.fragment or u.query or u.port not in (None,443):
        raise ValueError('Expected a clean HTTPS URL')
    for addr in socket.getaddrinfo(u.hostname,443,type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(addr[4][0]).is_global: raise ValueError('OIDC host must have a public IP')
    return value.rstrip('/')
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args): raise ValueError('OIDC redirect forbidden')
def fetch(url, data=None):
    public_url(url.split('?',1)[0])
    req=Request(url,data=data,headers={'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'})
    with build_opener(NoRedirect).open(req,timeout=8) as response:
        if response.status!=200 or int(response.headers.get('Content-Length','0'))>65536: raise ValueError('Invalid OIDC response')
        body=response.read(65537)
    if len(body)>65536: raise ValueError('OIDC response too large')
    return json.loads(body)
def discovery(config):
    issuer=public_url(config['issuer_url'])
    # Standard OIDC discovery path for issuers with a path component.
    meta=fetch(issuer+'/.well-known/openid-configuration')
    if meta.get('issuer')!=issuer: raise ValueError('OIDC issuer mismatch')
    for key in ('authorization_endpoint','token_endpoint','jwks_uri'):
        if not isinstance(meta.get(key),str): raise ValueError('Missing OIDC endpoint')
        public_url(meta[key])
    if 'RS256' not in meta.get('id_token_signing_alg_values_supported',['RS256']): raise ValueError('RS256 not supported')
    return meta
def sign(value,secret):
    return b64(hmac.new(bytes.fromhex(secret),value.encode(),hashlib.sha256).digest())
def pack(value,secret):
    raw=b64(json.dumps(value,separators=(',',':')).encode())
    return raw+'.'+sign(raw,secret)
def unpack(value,secret):
    raw,mac=value.split('.',1)
    if not hmac.compare_digest(mac,sign(raw,secret)): raise ValueError('Invalid state cookie')
    return json.loads(unb64(raw))
def start(config, origin):
    meta=discovery(config)
    state=secrets.token_urlsafe(24); nonce=secrets.token_urlsafe(24); verifier=secrets.token_urlsafe(48)
    challenge=b64(hashlib.sha256(verifier.encode()).digest())
    redirect=origin+'/auth/oidc/callback'
    params=dict(response_type='code',client_id=config['client_id'],redirect_uri=redirect,scope='openid profile email',state=state,nonce=nonce,code_challenge=challenge,code_challenge_method='S256')
    pending=pack(dict(state=state,nonce=nonce,verifier=verifier,issued=int(time.time()),redirect=redirect),config['session_secret'])
    return meta['authorization_endpoint']+'?'+urlencode(params),pending
def _der_length(n):
    return bytes([n]) if n<128 else bytes([0x80+((n.bit_length()+7)//8)])+n.to_bytes((n.bit_length()+7)//8,'big')
def _der(tag,data):
    return bytes([tag])+_der_length(len(data))+data
def _int(raw):
    raw=raw.lstrip(b'\\x00') or b'\\x00'
    if raw[0]&128: raw=b'\\x00'+raw
    return _der(2,raw)
def verify_id_token(token, config, meta, nonce):
    head,body,sig=token.split('.')
    header=json.loads(unb64(head)); claims=json.loads(unb64(body))
    if header.get('alg')!='RS256' or not isinstance(header.get('kid'),str): raise ValueError('Unsupported ID token')
    keys=fetch(meta['jwks_uri']).get('keys',[])
    key=next((k for k in keys if k.get('kid')==header['kid'] and k.get('kty')=='RSA' and k.get('use','sig')=='sig'),None)
    if not key: raise ValueError('No matching signing key')
    n=unb64(key['n']); e=unb64(key['e'])
    rsa=_der(0x30,_int(n)+_int(e))
    algorithm=_der(0x30,_der(6,bytes.fromhex('2a864886f70d010101'))+_der(5,b''))
    spki=_der(0x30,algorithm+_der(3,b'\\x00'+rsa))
    pem=b'-----BEGIN PUBLIC KEY-----\\n'+base64.encodebytes(spki)+b'-----END PUBLIC KEY-----\\n'
    with tempfile.TemporaryDirectory() as d:
        Path(d,'key.pem').write_bytes(pem);Path(d,'sig').write_bytes(unb64(sig))
        result=subprocess.run(['openssl','dgst','-sha256','-verify',str(Path(d,'key.pem')),'-signature',str(Path(d,'sig'))],input=(head+'.'+body).encode(),capture_output=True,timeout=5)
    if result.returncode: raise ValueError('Invalid ID token signature')
    now=int(time.time())
    aud=claims.get('aud',[])
    if claims.get('iss')!=meta['issuer'] or config['client_id'] not in (aud if isinstance(aud,list) else [aud]): raise ValueError('Invalid ID token audience/issuer')
    if isinstance(aud,list) and len(aud)>1 and claims.get('azp')!=config['client_id']: raise ValueError('Invalid authorized party')
    if not isinstance(claims.get('exp'),int) or claims['exp']<=now-60 or not isinstance(claims.get('iat'),int) or claims['iat']>now+60: raise ValueError('Expired or invalid ID token')
    if not hmac.compare_digest(str(claims.get('nonce','')),nonce) or not claims.get('sub'): raise ValueError('Invalid nonce or subject')
    return claims
def callback(config, origin, code, state, pending):
    data=unpack(pending,config['session_secret'])
    if int(time.time())-data['issued']>300 or not hmac.compare_digest(state,data['state']) or data['redirect']!=origin+'/auth/oidc/callback': raise ValueError('Invalid OIDC state')
    meta=discovery(config)
    secret=config.get('client_secret','')
    if not secret: raise ValueError('Missing OIDC client secret')
    form=urlencode(dict(grant_type='authorization_code',code=code,redirect_uri=data['redirect'],client_id=config['client_id'],client_secret=secret,code_verifier=data['verifier'])).encode()
    token=fetch(meta['token_endpoint'],form)
    return verify_id_token(token['id_token'],config,meta,data['nonce'])
