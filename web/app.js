let csrf='';
const fields=[['enabled','Автоматический сон','bool'],['charge_control_enabled','Управлять зарядкой Lenovo (экспериментально)','bool'],['charge_lower_percent','Возобновить зарядку при, %','int'],['charge_upper_percent','Включить Conservation Mode при, %','int'],['sleep_threshold','Порог сна, %','int'],['low_threshold','Экономный режим, %','int'],['critical_threshold','Критический заряд, %','int'],['normal_wake_minutes','Пробуждение, минут','int'],['low_wake_minutes','Редкое пробуждение, минут','int'],['check_seconds','Проверка, секунд','int'],['shutdown_timeout','Остановка гостей, секунд','int'],['force_stop_sleep','Принудительно останавливать гостей после тайм-аута','bool'],['force_stop_low','Принудительно останавливать гостей после тайм-аута','bool'],['manage_vms','Управлять VM','bool'],['minimum_restore_percent','Минимальный заряд для восстановления, %','int'],['critical_action','Критическое действие (poweroff/warn)','str'],['hdd_spindown_enabled','Останавливать HDD после остановки гостей','bool']];
const settingsGroups=[
  {title:'Жёсткий диск',description:'Остановка HDD после остановки гостей и размонтирования /mnt/storage. Выбери один или несколько обнаруженных дисков.',keys:['hdd_spindown_enabled']},
  {title:'Управление зарядом аккумулятора',description:'Lenovo Conservation Mode и пороги управления зарядом.',keys:['charge_control_enabled','charge_lower_percent','charge_upper_percent']},
  {title:'Управление отключением/включением сервера',description:'Настройки автоматического сна и восстановления гостей.',toggle:'enabled',sections:[
    {title:'Экономный режим',description:'Когда переходить в сон и через сколько минут просыпаться.',keys:['sleep_threshold','normal_wake_minutes','force_stop_sleep']},
    {title:'Критический режим',description:'Порог энергосбережения и увеличенный интервал сна.',keys:['low_threshold','low_wake_minutes','force_stop_low']},
    {title:'Остановка и восстановление контейнеров',description:'Проверка фактической остановки гостей перед сном обязательна.',keys:['shutdown_timeout','manage_vms','minimum_restore_percent']},
    {title:'Мониторинг питания',description:'Как часто проверять питание, пока сервер работает.',keys:['check_seconds']},
    {title:'Аварийная защита',description:'Отдельный критический порог и действие при почти разряженной батарее.',keys:['critical_threshold','critical_action']}
  ]}
];
let discoveredHdds=[];
let selectedHdds=[];
function renderSettings(cfg){
  selectedHdds=(cfg.hdd_disks||[]).map(x=>({...x}));
  const root=el('settings');root.replaceChildren();
  const definitions=new Map(fields.map(field=>[field[0],field]));
  function addFields(container,keys){
    for(const key of keys){
      const field=definitions.get(key);if(!field)continue;
      const [,label,type]=field;
      const row=document.createElement('label');row.textContent=label;
      const inp=document.createElement(type==='choice'?'select':'input');inp.id='cfg-'+key;
      if(type==='choice'){
        for(const [value,title] of [['never','Не останавливать принудительно'],['low','При экономном пороге (15%)'],['sleep','При пороге сна (30%)']]){
          const option=document.createElement('option');option.value=value;option.textContent=title;inp.append(option);
        }
        inp.value=cfg[key]??'never';
      }else{
        inp.type=type==='bool'?'checkbox':type==='str'?'text':'number';
        if(type==='bool')inp.checked=cfg[key]===true;
        else inp.value=cfg[key]??'';
      }
      row.append(inp);container.append(row);
    }
  }
  for(const group of settingsGroups){
    const details=document.createElement('details');details.className='settings-group';details.open=true;
    const summary=document.createElement('summary');summary.textContent=group.title;details.append(summary);
    const hint=document.createElement('p');hint.className='settings-hint';hint.textContent=group.description;details.append(hint);
    if(group.toggle){
      const toggleWrap=document.createElement('div');toggleWrap.className='settings-toggle';
      addFields(toggleWrap,[group.toggle]);details.append(toggleWrap);
      const body=document.createElement('div');body.className='settings-dependent';
      for(const section of group.sections){
        const nested=document.createElement('details');nested.className='settings-subgroup';nested.open=true;
        const heading=document.createElement('summary');heading.textContent=section.title;nested.append(heading);
        const help=document.createElement('p');help.className='settings-hint';help.textContent=section.description;nested.append(help);
        addFields(nested,section.keys);body.append(nested);
      }
      const toggle=toggleWrap.querySelector('input');
      const sync=()=>{body.hidden=!toggle.checked};
      toggle.addEventListener('change',sync);sync();details.append(body);
    }else addFields(details,group.keys);
    if(group.title==='Жёсткий диск'){
      const list=document.createElement('div');
      for(const disk of discoveredHdds){
        const line=document.createElement('label');
        const check=document.createElement('input');check.type='checkbox';
        check.checked=selectedHdds.some(x=>x.device===disk.device&&x.mountpoint===disk.mountpoint);
        check.onchange=()=>{selectedHdds=selectedHdds.filter(x=>!(x.device===disk.device&&x.mountpoint===disk.mountpoint));if(check.checked)selectedHdds.push({device:disk.device,mountpoint:disk.mountpoint})};
        line.append(check,document.createTextNode(' '+(disk.model||disk.device)+' · '+(disk.size?Math.round(disk.size/1e9)+' GB · ':'')+disk.mountpoint));list.append(line);
      }
      if(!discoveredHdds.length)list.textContent='Подходящие HDD не обнаружены';
      details.append(list);
      const btn=document.createElement('button');btn.type='button';btn.textContent='Принудительно запустить HDD и смонтировать';
      btn.onclick=async()=>{btn.disabled=true;try{await request('hdd/start',{});el('message').textContent='HDD запущен и смонтирован';await refresh()}catch(e){el('message').textContent='Ошибка запуска HDD: '+e.message}finally{btn.disabled=false}};
      details.append(btn);
    }
    root.append(details);
  }
}
const el=id=>document.getElementById(id);
async function request(path,data){const r=await fetch('/api/'+path,{method:data===undefined?'GET':'POST',credentials:'same-origin',headers:data===undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:data===undefined?undefined:JSON.stringify(data)});const j=await r.json();if(!r.ok||j.error)throw Error(j.error||'HTTP '+r.status);return j}
async function busy(id,fn){const btn=el(id);if(btn.disabled)return;const old=btn.textContent;btn.disabled=true;btn.replaceChildren();const spin=document.createElement('span');spin.className='spinner';spin.setAttribute('aria-hidden','true');btn.append(spin,document.createTextNode('Загрузка...'));try{return await fn()}finally{btn.disabled=false;btn.textContent=old}}
function duration(minutes){
  if(!Number.isFinite(minutes)||minutes<0)return 'Нет данных';
  const h=Math.floor(minutes/60),m=Math.round(minutes%60);
  return h? h+' ч '+m+' мин':m+' мин';
}
function renderInfo(status){
  const root=el('status');root.replaceChildren();
  const info=status.battery_info||{}, charge=status.charge_control||{};
  const cards=document.createElement('div');cards.className='info-grid';
  function card(label,value,note){
    const c=document.createElement('div');c.className='info-card';
    const title=document.createElement('div');title.className='caption';title.textContent=label;
    const metric=document.createElement('div');metric.className='metric';metric.textContent=value;
    const detail=document.createElement('div');detail.className='caption';detail.textContent=note;
    c.append(title,metric,detail);cards.append(c);
  }
  card('Электросеть',status.ac_online?'Подключена':'Отключена',status.ac_online?'Питание от сети':'Питание от аккумулятора');
  card('Аккумулятор',status.battery_percent+'%',({Charging:'Заряжается',Discharging:'Разряжается',Full:'Полный заряд','Not charging':'Не заряжается'})[info.status]||info.status||'Статус неизвестен');
  const time=info.status==='Discharging'?info.time_remaining_minutes:info.status==='Charging'?info.time_to_target_minutes:null;
  card(info.status==='Discharging'?'Осталось работать':info.status==='Charging'?'До '+(info.target_percent??100)+'%':'Прогноз времени',duration(time),time===null?'Недостаточно данных':'При текущей скорости, приблизительно');
  card('Мощность аккумулятора',info.power_w!=null?Number(info.power_w).toLocaleString('ru-RU',{maximumFractionDigits:2})+' Вт':'Нет данных',info.status==='Discharging'?'Расход от батареи':info.status==='Charging'?'Мощность зарядки':'Не измеряет расход из розетки');
  card('Работающие гости',(status.running_containers||[]).length+' LXC / '+(status.running_vms||[]).length+' VM','Восстановление: '+(status.saved_state?'ожидается':'не требуется'));
  root.append(cards);
  const track=document.createElement('div');track.className='battery-track';
  const fill=document.createElement('div');fill.className='battery-fill';fill.style.width=Math.max(0,Math.min(100,Number(status.battery_percent)||0))+'%';
  track.append(fill);root.append(track);
  const details=document.createElement('div');details.className='system-status';
  const heading=document.createElement('h3');heading.textContent='Состояние системы';details.append(heading);
  function statusRow(label,value,active){
    const row=document.createElement('div');row.className='system-status-row';
    const name=document.createElement('span');name.className='system-status-label';name.textContent=label;
    const state=document.createElement('span');state.className='system-status-value';
    if(active!==null){state.classList.add('system-status-indicator');state.classList.add(active?'is-active':'is-inactive')}
    state.textContent=value;row.append(name,state);details.append(row);
  }
  const mode=charge.supported?(charge.mode===1?'Long Life':charge.mode===0?'Standard':'Неизвестен'):'Не поддерживается';
  statusRow('Conservation Mode',mode,charge.supported?charge.mode===1:null);
  statusRow('Управление зарядкой',charge.enabled?'Включено':'Выключено',Boolean(charge.enabled));
  statusRow('Автоматический сон',status.enabled?'Включён':'Выключен',Boolean(status.enabled));
  const lxc=Array.isArray(status.running_containers)?status.running_containers:[];
  const vms=Array.isArray(status.running_vms)?status.running_vms:[];
  function guestRow(label,ids){
    const wrap=document.createElement('div');wrap.className='system-guests';
    const header=document.createElement('div');header.className='system-status-row';
    const name=document.createElement('span');name.className='system-status-label';name.textContent=label;
    const count=document.createElement('span');count.className='system-status-value';count.textContent=ids.length+' '+(label==='LXC'?'контейнеров':'VM');
    header.append(name,count);wrap.append(header);
    const chips=document.createElement('div');chips.className='guest-chips';
    if(!ids.length){const empty=document.createElement('span');empty.className='system-status-label';empty.textContent='Нет работающих';chips.append(empty)}
    for(const id of ids){const chip=document.createElement('span');chip.className='guest-chip';chip.textContent=String(id);chips.append(chip)}
    wrap.append(chips);details.append(wrap);
  }
  guestRow('LXC',lxc);
  if(vms.length)guestRow('Виртуальные машины',vms);
  if(status.saved_state)statusRow('Восстановление гостей','Ожидается',null);
  root.append(details);
}
function renderHistory(data){
  const root=el('history');root.replaceChildren();
  const events=(data.events||[]).slice().reverse();
  if(!events.length){root.textContent='Сегодня событий пока нет';return}
  const titles={AC_LOST:'Электричество отключено',AC_RESTORED:'Электричество восстановлено',
    BATTERY_STATUS:'Изменение состояния зарядки',CONSERVATION_CHANGED:'Режим аккумулятора изменён',
    BATTERY_THRESHOLD:'Достигнут порог заряда',SLEEP_STARTED:'Сервер переходит в сон',
    SERVER_WOKE:'Сервер проснулся',GUESTS_RESTORED:'Контейнеры восстановлены'};
  const statuses={Charging:'Заряжается',Discharging:'Разряжается',Full:'Полный заряд','Not charging':'Не заряжается'};
  for(const event of events){
    const item=document.createElement('div');item.className='history-item';
    const time=document.createElement('div');time.className='history-time';
    time.textContent=new Date(event.timestamp_ms).toLocaleTimeString('ru-RU');
    const title=document.createElement('strong');title.textContent=titles[event.type]||event.type;
    const reason=document.createElement('div');reason.className='history-reason';
    const parts=[];
    if(event.reason)parts.push(event.reason);
    if(event.status)parts.push(statuses[event.status]||event.status);
    if(event.battery_percent!=null)parts.push('Заряд: '+event.battery_percent+'%');
    if(event.duration_minutes!=null)parts.push('Сон: '+event.duration_minutes+' мин');
    if(event.mode!=null)parts.push('Conservation Mode: '+(event.mode===1?'Long Life':'Standard'));
    reason.textContent=parts.join(' · ');
    item.append(time,title,reason);root.append(item);
  }
}
const tabs=['overview','history','settings'];
function selectTab(name,focus=false){
  if(!tabs.includes(name))return;
  for(const tab of tabs){
    const active=tab===name;
    const button=el('tab-'+tab);
    button.setAttribute('aria-selected',String(active));
    button.tabIndex=active?0:-1;
    el('panel-'+tab).hidden=!active;
  }
  if(focus)el('tab-'+name).focus();
}
for(const [i,name] of tabs.entries()){
  el('tab-'+name).addEventListener('click',()=>selectTab(name));
  el('tab-'+name).addEventListener('keydown',event=>{
    const next=event.key==='ArrowRight'?tabs[(i+1)%tabs.length]:
      event.key==='ArrowLeft'?tabs[(i+tabs.length-1)%tabs.length]:
      event.key==='Home'?tabs[0]:event.key==='End'?tabs[tabs.length-1]:null;
    if(next){event.preventDefault();selectTab(next,true)}
  });
}
function showLogin(show){el('login-panel').hidden=!show;el('dashboard').hidden=show}
async function checkSession(){try{const s=await request('session');csrf=s.csrf||'';showLogin(!s.authenticated);if(s.authenticated)await refresh()}catch(e){showLogin(true);el('login-error').textContent=e.message}}
async function refresh(){el('status').textContent='Загрузка состояния...';try{const [status,cfg,history,disks]=await Promise.all([request('status'),request('config'),request('history').catch(e=>({error:e.message})),request('hdd/disks').catch(()=>({disks:[]}))]);discoveredHdds=disks.disks||[];renderInfo(status);renderSettings(cfg);if(history.error)el('history').textContent='Не удалось загрузить историю: '+history.error;else renderHistory(history)}catch(e){el('status').textContent='Не удалось загрузить состояние';el('message').textContent=e.message;if(e.message.includes('Authentication'))showLogin(true)}}
el('login').onclick=()=>busy('login',async()=>{try{const r=await request('login',{username:el('username').value,password:el('password').value});csrf=r.csrf;el('password').value='';el('login-error').textContent='';showLogin(false);await refresh()}catch(e){el('login-error').textContent=e.message}});
el('logout').onclick=()=>busy('logout',async()=>{try{await request('logout',{})}finally{csrf='';showLogin(true)}});
el('refresh').onclick=()=>busy('refresh',refresh);
el('save').onclick=()=>busy('save',async()=>{const payload={};for(const [key,,type] of fields){const inp=el('cfg-'+key);if(!inp){el('message').textContent='Сначала войдите';return}payload[key]=type==='bool'?inp.checked:(type==='str'||type==='choice')?inp.value:Number(inp.value)}payload.hdd_disks=selectedHdds;try{await request('config',payload);el('message').textContent='Настройки сохранены';await refresh()}catch(e){el('message').textContent=e.message}});

checkSession();
