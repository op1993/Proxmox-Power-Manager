"""Telegram notifications, configured on the Proxmox host; no credentials in logs."""
import json
import logging
import os
import re
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LOG = logging.getLogger('ppm.telegram')
CONFIG = Path('/etc/proxmox-power-manager/telegram.json')
DEFAULT = {'enabled': False, 'ac_lost': True, 'ac_restored': True,
           'dns': True, 'sleep': True, 'wake': True, 'fully_restored': True}

def _read():
    try:
        obj=json.loads(CONFIG.read_text())
        return obj if isinstance(obj,dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}

def settings():
    data={**DEFAULT,**_read()}
    data.pop('bot_token',None)
    data['token_configured']=bool(_read().get('bot_token'))
    return data

def save(payload):
    allowed=set(DEFAULT)|{'bot_token','chat_id'}
    if not isinstance(payload,dict) or set(payload)-allowed:
        raise ValueError('Unsupported Telegram setting')
    data={**DEFAULT,**_read()}
    for key,value in payload.items():
        if key in DEFAULT:
            if type(value) is not bool: raise ValueError('Invalid Telegram toggle')
        elif not isinstance(value,str) or len(value)>256: raise ValueError('Invalid Telegram credential')
        if key!='bot_token' or value: data[key]=value
    token=data.get('bot_token','')
    chat=str(data.get('chat_id',''))
    if token and not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+',token):
        raise ValueError('Invalid Telegram bot token')
    if chat and not re.fullmatch(r'-?[0-9]+',chat):
        raise ValueError('Chat ID must be numeric')
    if data['enabled'] and (not token or not chat):
        raise ValueError('Bot token and chat ID required')
    CONFIG.parent.mkdir(parents=True,exist_ok=True)
    tmp=CONFIG.with_suffix('.tmp')
    try:
        with open(tmp,'w') as f:
            json.dump(data,f);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o600)
        os.replace(tmp,CONFIG)
    finally: tmp.unlink(missing_ok=True)
    return settings()

def send(message, kind=None, force=False):
    data=_read()
    if not force and (not data.get('enabled') or (kind and not data.get(kind,True))):
        return False
    if not data.get('bot_token') or not data.get('chat_id'):
        return False
    # POST body, not URL parameters, keeps credentials out of access logs and command lines.
    token=data['bot_token']
    body=urlencode({'chat_id':data['chat_id'],'text':message[:3500],
                    'disable_web_page_preview':'true'}).encode()
    try:
        req=Request('https://api.telegram.org/bot'+token+'/sendMessage',
                    data=body,method='POST')
        with urlopen(req,timeout=5) as response:
            result=json.load(response)
        if not result.get('ok'): raise ValueError('Telegram API rejected message')
        return True
    except Exception as exc:
        # Never include exception details: request URL contains the bot token.
        LOG.warning('Telegram delivery failed (%s)',type(exc).__name__)
        return False
