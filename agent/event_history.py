"""Read today's power events from the existing system journal."""
import json
import subprocess

PREFIX = 'PPM_EVENT '

def today():
    result = subprocess.run(
        ['journalctl', '-u', 'proxmox-power-manager.service', '--since', 'today',
         '--output=json', '--no-pager', '-n', '5000'],
        capture_output=True, text=True, timeout=12, check=True)
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
    return {'events': events[-500:]}
