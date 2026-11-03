
const token = "__TOKEN__";
let params, busy=false, connected=false, saving=Promise.resolve(), dirty=false;
const $=id=>document.getElementById(id);
async function api(path, data) {
  const r=await fetch('/api/'+path, data===undefined ? {cache:'no-store'} : {method:'POST',headers:{'Content-Type':'application/json','X-Control-Token':token},body:JSON.stringify(data)});
  const b=await r.json(); if(!r.ok || !b.ok) throw Error(b.error||'请求失败'); return b;
}
function notice(e){$('error').textContent=e.message||e;}
function edit(){dirty=true; $('save-status').textContent='参数尚未保存';}
function capture(){
  const p=JSON.parse(JSON.stringify(params));
  p.manual_ms=Number($('manual').value);
  document.querySelectorAll('[data-pos]').forEach(e=>p.poses[e.dataset.pose][Number(e.dataset.pos)]=Number(e.value));
  document.querySelectorAll('[data-time]').forEach(e=>p[e.dataset.time][Number(e.dataset.phase)]=Number(e.value));
  return p;
}
function save(){
  const p=capture(); params=p; dirty=false;
  saving=saving.catch(()=>{}).then(()=>api('settings',{params:p}));
  saving.then(()=>{$('save-status').textContent='参数已自动保存到本机';},e=>{$('save-status').textContent='保存失败：'+e.message;});
  warning();
}
function warning(){const p=capture(); const phases=p.wait_ms.map((v,i)=>v<p.move_ms[i]?i:null).filter(v=>v!==null);$('timing-warning').textContent=phases.length?'注意：Phase '+phases.join('、')+' 的等待短于运动时间，下一阶段可能打断运动。':'';}
function render(b){
 params=b.params; $('manual').value=params.manual_ms; $('device').value=b.device;
 for(const [name,label] of Object.entries(b.labels)){
   const card=document.createElement('article');card.className='pose-card';
   const title=document.createElement('h2');title.textContent=label;card.append(title);
   const list=document.createElement('div');list.className='slider-list';card.append(list);
   params.poses[name].forEach((v,i)=>{
     const row=document.createElement('label');row.className='slider-row';
     row.innerHTML=`<span class="slider-name">${String(i).padStart(3,'0')}</span><input type="range" min="500" max="2500" step="1"><input class="position-number" type="number" min="500" max="2500" step="1" aria-label="${label} 舵机 ${i} 位置">`;
     const [slider,number]=row.querySelectorAll('input');slider.value=number.value=v;number.dataset.pos=i;number.dataset.pose=name;
     slider.oninput=()=>{number.value=slider.value;edit();};slider.onchange=save;
     number.oninput=()=>{slider.value=number.value;edit();};number.onchange=save;list.append(row);
   });
   const btn=document.createElement('button');btn.className='primary-button motion';btn.textContent='执行此姿态';btn.onclick=()=>act('move',{pose:name});card.append(btn);$('cards').append(card);
 }
 ['吸取','转移','下降','释放','复位'].forEach((label,i)=>{
 const el=document.createElement('div');el.className='timing-control';
 el.innerHTML=`<b>Phase ${i} · ${label}</b><label>运动 T <input type="number" min="0" max="9999" data-time="move_ms" data-phase="${i}" value="${params.move_ms[i]}"> ms</label><label>发送后等待 <input type="number" min="0" max="60000" data-time="wait_ms" data-phase="${i}" value="${params.wait_ms[i]}"> ms</label>`;
 el.querySelectorAll('input').forEach(e=>{e.oninput=edit;e.onchange=save;});$('timing').append(el);
 });
 $('manual').oninput=edit;$('manual').onchange=save;warning();status(b);
}
function status(b){
 busy=b.busy; connected=b.connected;
 $('status').textContent=(b.demo?'演示模式 · 不控制硬件':(connected?'实机模式 · 串口已打开':'实机模式 · 串口未连接'))+(busy?' · 执行中':'')+(b.fault?' · 故障':'');
 $('message').textContent=b.message;
 $('pump').textContent='005 最近发送值：'+(b.pump_position===null?'未知':String(b.pump_position).padStart(4,'0'))+'（无状态回读）';
 $('logs').textContent=b.logs.join('\n');
 document.querySelectorAll('.motion, #reset, #sequence, #on, #off, #neutral').forEach(e=>e.disabled=busy||!connected||!!b.fault);
 document.querySelectorAll('#on, #off, #neutral').forEach(e=>e.disabled=busy||!connected||!!b.fault||!b.pump_available);
 $('connect').disabled=busy;$('device').disabled=busy;$('stop').disabled=!connected;
 const options=b.ports.join('|');if($('ports').dataset.values!==options){$('ports').replaceChildren(...b.ports.map(p=>{const o=document.createElement('option');o.value=p;return o;}));$('ports').dataset.values=options;}
}
async function act(action, extra={}){
 $('error').textContent='';
 try{const p=capture();await api('action',{action,params:p,target:$('target').value,...extra});status(await api('state'));}catch(e){notice(e);}
}
$('connect').onclick=async()=>{$('error').textContent='';try{await api('connect',{device:$('device').value});status(await api('state'));}catch(e){notice(e);}};
$('reset').onclick=()=>act('move',{pose:'reset'});$('sequence').onclick=()=>act('sequence');
$('on').onclick=()=>act('pump_on');$('off').onclick=()=>act('pump_off');$('neutral').onclick=()=>act('pump_reset');
$('stop').onclick=async()=>{try{await api('stop',{});status(await api('state'));}catch(e){notice(e);}};
async function poll(){try{status(await api('state'));}catch(e){$('status').textContent='页面与服务连接中断';document.querySelectorAll('button').forEach(b=>b.disabled=true);}setTimeout(poll,800);}
api('state').then(b=>{render(b);setTimeout(poll,800);}).catch(notice);
