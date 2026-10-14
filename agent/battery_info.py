"""Read-only battery telemetry and conservative time estimates."""
from pathlib import Path

def _read(root, name):
    try:
        value=(root/name).read_text().strip()
        return value if value else None
    except (OSError, ValueError):
        return None

def _number(root, name):
    try:
        value=float(_read(root,name))
        return value if value>=0 else None
    except (TypeError,ValueError):
        return None

def snapshot(battery_path, target_percent=100):
    root=Path(battery_path).parent
    status=_read(root,'status') or 'Unknown'
    capacity=_number(root,'capacity')
    energy=_number(root,'energy_now')
    full=_number(root,'energy_full')
    rate=_number(root,'power_now')
    units='uWh'
    if energy is None or full is None:
        energy=_number(root,'charge_now')
        full=_number(root,'charge_full')
        rate=_number(root,'current_now')
        units='uAh'
    if rate is None or rate<=0: rate=None
    result={'status':status,'capacity_percent':capacity,
            'energy_now_wh':round(energy/1e6,2) if units=='uWh' and energy is not None else None,
            'energy_full_wh':round(full/1e6,2) if units=='uWh' and full is not None else None,
            'power_w':round(rate/1e6,2) if units=='uWh' and rate is not None else None,
            'time_remaining_minutes':None,'time_to_target_minutes':None,
            'target_percent':target_percent,'estimate_available':False}
    if energy is None or full is None or rate is None or full<=0 or not 0<=target_percent<=100:
        return result
    if status=='Discharging':
        result['time_remaining_minutes']=round(energy/rate*60)
        result['estimate_available']=True
    elif status=='Charging':
        remaining=max(0,full*target_percent/100-energy)
        result['time_to_target_minutes']=round(remaining/rate*60)
        result['estimate_available']=True
    return result
