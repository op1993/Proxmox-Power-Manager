"""Emit power and battery transitions, not periodic status spam."""
import json
import logging
from pathlib import Path

LOG = logging.getLogger('ppm.events')
STATE = Path('/var/lib/proxmox-power-manager/observed.json')

def emit(kind, **details):
    LOG.info('PPM_EVENT %s', json.dumps(dict(type=kind, **details), ensure_ascii=False))
    mapping={'AC_LOST':('ac_lost','🔌 Питание отключено'),'AC_RESTORED':('ac_restored','⚡ Питание восстановлено'),'SLEEP_STARTED':('sleep','💤 Сервер уходит в сон'),'SERVER_WOKE':('wake','🌅 Сервер проснулся')}
    if kind in mapping:
        from telegram_notify import send
        setting,title=mapping[kind]
        battery=details.get('battery_percent')
        extra=('\\nЗаряд: '+str(battery)+'%') if battery is not None else ''
        send(title+extra,setting)

def observe(ac, battery, battery_status, conservation_mode, cfg):
    current = dict(ac=bool(ac), battery_status=battery_status,
                   conservation_mode=conservation_mode)
    try:
        previous = json.loads(STATE.read_text())
    except (OSError, ValueError):
        previous = None
    if previous is not None:
        if previous.get('ac') != current['ac']:
            emit('AC_RESTORED' if ac else 'AC_LOST', battery_percent=battery,
                 reason='Изменение состояния электросети')
        if previous.get('battery_status') != battery_status and battery_status in ('Charging', 'Discharging', 'Full', 'Not charging'):
            emit('BATTERY_STATUS', battery_percent=battery, status=battery_status,
                 reason='Изменение состояния зарядки')
        if previous.get('conservation_mode') != conservation_mode and conservation_mode is not None:
            emit('CONSERVATION_CHANGED', battery_percent=battery, mode=conservation_mode,
                 reason='Изменение Lenovo Conservation Mode')
        for key, threshold in [('sleep', cfg['sleep_threshold']), ('low', cfg['low_threshold']), ('critical', cfg['critical_threshold'])]:
            prior=previous.get('battery_percent')
            if isinstance(prior, int) and prior > threshold >= battery:
                emit('BATTERY_THRESHOLD', battery_percent=battery, threshold=threshold,
                     reason='Достигнут порог '+key)
    current['battery_percent'] = battery
    if previous != current:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix('.tmp')
        tmp.write_text(json.dumps(current))
        tmp.replace(STATE)
