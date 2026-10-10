"""Read-only power management scenario planner. No subprocesses or state writes."""
def simulate(cfg, actual, scenario):
    if not isinstance(scenario, dict) or set(scenario)-{'ac_online','battery_percent','simulate_enabled','recovery'}:
        raise ValueError('Invalid simulation parameters')
    ac=scenario.get('ac_online', actual['ac_online'])
    battery=scenario.get('battery_percent', actual['battery_percent'])
    enabled=scenario.get('simulate_enabled', cfg['enabled'])
    recovery=scenario.get('recovery', actual['saved_state'] is not None)
    if type(ac) is not bool or type(enabled) is not bool or type(recovery) is not bool:
        raise ValueError('Scenario flags must be booleans')
    if type(battery) is not int or not 0 <= battery <= 100:
        raise ValueError('Battery must be an integer between 0 and 100')
    cts=list(actual['running_containers'])
    vms=list(actual['running_vms'])
    steps=[]
    def add(kind, message): steps.append({'type':kind,'message':message})
    if ac:
        if recovery:
            if battery < cfg['minimum_restore_percent']:
                add('wait', 'AC restored; waiting for minimum battery charge before guest recovery')
            else:
                add('restore', 'Restore guests recorded in recovery state; clear state only after successful verification')
        else:
            add('idle', 'AC online; no recovery needed')
    elif not enabled:
        add('disabled', 'Automatic power management is disabled; no actions will run')
    elif battery <= cfg['critical_threshold']:
        add('critical', 'Critical threshold reached; attempt graceful guest shutdown')
        add('shutdown', 'Shutdown running guests and verify their state')
        add('critical_action', 'Configured critical action: '+cfg['critical_action'])
        if cfg['critical_action']=='poweroff':
            add('warning', 'Poweroff may not automatically boot when AC returns')
    elif not recovery and battery > cfg['sleep_threshold']:
        add('idle', 'Battery above sleep threshold; continue monitoring')
    else:
        interval=cfg['low_wake_minutes'] if battery <= cfg['low_threshold'] else cfg['normal_wake_minutes']
        if not recovery:
            add('record', 'Persist list of running guests for later restoration')
            add('shutdown', 'Gracefully shut down guests; abort suspend if any remain running')
        else:
            add('recovery', 'Existing recovery record: do not overwrite recorded guests')
        add('suspend', 'Request RTC suspend for '+str(interval)+' minutes if AC is still offline and guests are stopped')
    if any(x['type'] in ('shutdown','suspend','critical_action') for x in steps):
        add('safety', 'Simulation only: no pct, qm, rtcwake, systemctl, or state writes performed')
    return {'ok':True,'simulated':True,'scenario':{'ac_online':ac,'battery_percent':battery,'enabled':enabled,'recovery':recovery},'actual_status':actual,'guests':{'running_containers':cts,'running_vms':vms},'steps':steps}
