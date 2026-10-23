"""Read power events for a selected local calendar day from systemd journal."""
import datetime
from router_dns_history import read as read_router_history
import json
import subprocess

PREFIX = 'PPM_EVENT '

def for_date(date_text):
    if not isinstance(date_text, str):
        raise ValueError('Date must be YYYY-MM-DD')
    try:
        day = datetime.date.fromisoformat(date_text)
        if day.isoformat() != date_text:
            raise ValueError()
    except ValueError:
        raise ValueError('Date must be YYYY-MM-DD')
    if day > datetime.date.today():
        raise ValueError('Future dates are not supported')
    start = day.isoformat() + ' 00:00:00'
    end = (day + datetime.timedelta(days=1)).isoformat() + ' 00:00:00'
    result = subprocess.run(
        ['journalctl', '-u', 'proxmox-power-manager.service',
         '--since', start, '--until', end, '--output=json', '--no-pager'],
        capture_output=True, text=True, timeout=15, check=True)
    events = []
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
            message = item.get('MESSAGE', '')
            pos = message.find(PREFIX)
            if pos < 0:
                continue
            event = json.loads(message[pos + len(PREFIX):])
            if not isinstance(event, dict) or not isinstance(event.get('type'), str):
                continue
            events.append({'timestamp_ms': int(item['__REALTIME_TIMESTAMP']) // 1000, **event})
        except (ValueError, TypeError, KeyError):
            continue
    # Merge router events already persisted independently of journald.
    for entry in read_router_history():
        try:
            timestamp = datetime.datetime.fromisoformat(entry['timestamp'])
            if timestamp.astimezone().date() != day:
                continue
            events.append({
                'timestamp_ms': int(timestamp.timestamp() * 1000),
                'type': 'ROUTER_DNS_APPLIED' if entry.get('status') == 'success' else 'ROUTER_DNS_FAILED',
                'dns_mode': entry.get('mode'),
                'dns_previous': entry.get('previous'),
                'reason': entry.get('reason'),
                'error': entry.get('error'),
            })
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    events.sort(key=lambda event: event['timestamp_ms'])
    return {'date': date_text, 'events': events[-1000:]}

def today():
    return for_date(datetime.date.today().isoformat())
