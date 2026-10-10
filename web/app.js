let csrf='';
const fields=[['enabled','Автоматический сон','bool'],['charge_control_enabled','Управлять зарядкой Lenovo (экспериментально)','bool'],['charge_lower_percent','Возобновить зарядку при, %','int'],['charge_upper_percent','Включить Conservation Mode при, %','int'],['sleep_threshold','Порог сна, %','int'],['low_threshold','Экономный режим, %','int'],['critical_threshold','Критический заряд, %','int'],['normal_wake_minutes','Пробуждение, минут','int'],['low_wake_minutes','Редкое пробуждение, минут','int'],['check_seconds','Проверка, секунд','int'],['shutdown_timeout','Остановка гостей, секунд','int'],['manage_vms','Управлять VM','bool'],['minimum_restore_percent','Минимальный заряд для восстановления, %','int'],['critical_action','Критическое действие (poweroff/warn)','str']];
const settingsGroups=[
  {title:'Управление зарядом аккумулятора',description:'Lenovo Conservation Mode: включение и пороги зарядки. Аппаратное ограничение может отличаться от заданного.',keys:['charge_control_enabled','charge_lower_percent','charge_upper_percent']},
  {title:'Управление отключением/включением сервера',description:'Автоматический сон, пробуждение, остановка и восстановление LXC/VM, критические пороги и дополнительные параметры.',keys:['enabled','sleep_threshold','low_threshold','critical_threshold','normal_wake_minutes','low_wake_minutes','minimum_restore_percent','manage_vms','shutdown_timeout','check_seconds','critical_action']}
];
function renderSettings(cfg){
  const root=el('settings');root.replaceChildren();
  const definitions=new Map(fields.map(field=>[field[0],field]));
  for(const group of settingsGroups){
    const details=document.createElement('details');details.className='settings-group';
    details.open=true;
    const summary=document.createElement('summary');summary.textContent=group.title;details.append(summary);
    const hint=document.createElement('p');hint.className='settings-hint';hint.textContent=group.description;details.append(hint);
    for(const key of group.keys){
      const field=definitions.get(key);if(!field)continue;
      const [,label,type]=field;
      const row=document.createElement('label');row.textContent=label;
      const inp=document.createElement('input');inp.id='cfg-'+key;
      inp.type=type==='bool'?'checkbox':type==='str'?'text':'number';
      if(type==='bool')inp.checked=cfg[key]===true;
      else inp.value=cfg[key]??'';
      row.append(inp);details.append(row);
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
  const details=document.createElement('div');details.className='info-details';
  const items=[
    'Conservation Mode: '+(charge.supported?(charge.mode===1?'Long Life':charge.mode===0?'Standard':'неизвестен'):'не поддерживается'),
    'Автоматическое управление зарядкой: '+(charge.enabled?'включена':'выключена'),
    'Автоматическое управление питанием сервера: '+(status.enabled?'включён':'выключен'),
    'LXC: '+((status.running_containers||[]).join(', ')||'нет')
  ];
  if(info.power_w!=null)items.push('Мощность батареи: '+info.power_w+' Вт');
  for(const item of items){const span=document.createElement('span');span.textContent=item;details.append(span)}
  root.append(details);
}
function showLogin(show){el('login-panel').hidden=!show;el('dashboard').hidden=show}
async function checkSession(){try{const s=await request('session');csrf=s.csrf||'';showLogin(!s.authenticated);if(s.authenticated)await refresh()}catch(e){showLogin(true);el('login-error').textContent=e.message}}
async function refresh(){el('status').textContent='Загрузка состояния...';try{const [status,cfg]=await Promise.all([request('status'),request('config')]);renderInfo(status);renderSettings(cfg)}catch(e){el('status').textContent='Не удалось загрузить состояние';el('message').textContent=e.message;if(e.message.includes('Authentication'))showLogin(true)}}
el('login').onclick=()=>busy('login',async()=>{try{const r=await request('login',{username:el('username').value,password:el('password').value});csrf=r.csrf;el('password').value='';el('login-error').textContent='';showLogin(false);await refresh()}catch(e){el('login-error').textContent=e.message}});
el('logout').onclick=()=>busy('logout',async()=>{try{await request('logout',{})}finally{csrf='';showLogin(true)}});
el('refresh').onclick=()=>busy('refresh',refresh);
el('save').onclick=()=>busy('save',async()=>{const payload={};for(const [key,,type] of fields){const inp=el('cfg-'+key);if(!inp){el('message').textContent='Сначала войдите';return}payload[key]=type==='bool'?inp.checked:type==='str'?inp.value:Number(inp.value)}try{await request('config',payload);el('message').textContent='Настройки сохранены';await refresh()}catch(e){el('message').textContent=e.message}});
el('dry').onclick=()=>busy('dry',async()=>{el('simulation').textContent='Расчёт сценария...';try{const r=await request('dry-run',{ac_online:el('sim-ac').value==='true',battery_percent:Number(el('sim-battery').value),simulate_enabled:el('sim-enabled').checked,recovery:el('sim-recovery').checked});const lines=[`Сценарий: AC ${r.scenario.ac_online?'Online':'Offline'}, батарея ${r.scenario.battery_percent}%, автоматизация ${r.scenario.enabled?'включена':'выключена'}`,`Работающие LXC: ${r.guests.running_containers.join(', ')||'нет'}`,`Работающие VM: ${r.guests.running_vms.join(', ')||'нет'}`,'',...r.steps.map((x,i)=>`${i+1}. ${x.message}`)];el('simulation').textContent=lines.join('\n')}catch(e){el('simulation').textContent='Ошибка: '+e.message}});
checkSession();
