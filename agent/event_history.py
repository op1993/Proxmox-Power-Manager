"""Read power events for a selected local calendar day from systemd journal."""
import datetime
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
    return {'date': date_text, 'events': events[-1000:]}

def today():
    return for_date(datetime.date.today().isoformat())
