"""Conservative Lenovo charge mode controller; disabled by default."""
from pathlib import Path
import logging

LOG=logging.getLogger('ppm.charge')
CANDIDATES=(
 '/sys/bus/platform/drivers/ideapad_acpi/VPC2004:00/conservation_mode',
 '/sys/bus/platform/devices/VPC2004:00/conservation_mode',
 '/sys/bus/platform/drivers/ideapad_acpi/ideapad_acpi/conservation_mode',
)
def device():
    for p in CANDIDATES:
        if Path(p).is_file(): return Path(p)
    return None

def report(cfg):
    p=device()
    try: mode=int(p.read_text().strip()) if p else None
    except (OSError,ValueError): mode=None
    return {'supported':p is not None,'enabled':cfg.get('charge_control_enabled',False),
            'mode':mode,'lower':cfg.get('charge_lower_percent',70),
            'upper':cfg.get('charge_upper_percent',80),
            'note':'Conservation Mode uses firmware-defined limits; upper threshold is not guaranteed.'}

def tick(cfg):
    if not cfg.get('charge_control_enabled',False): return
    p=device()
    if p is None:
        LOG.warning('Charge control unsupported: conservation_mode not found')
        return
    try:
        # Never switch modes while running on battery.
        if not cfg['ac_path'] or int(Path(cfg['ac_path']).read_text().strip())!=1: return
        percent=int(Path(cfg['battery_path']).read_text().strip())
        current=int(p.read_text().strip())
        if current not in (0,1) or not 0<=percent<=100: return
        target=1 if percent>=cfg['charge_upper_percent'] else 0 if percent<=cfg['charge_lower_percent'] else current
        if target!=current:
            p.write_text(str(target)+'\n')
            LOG.info('Conservation mode changed to %s at %s%%',target,percent)
    except (OSError,ValueError) as e:
        LOG.warning('Charge control unavailable: %s',e)
