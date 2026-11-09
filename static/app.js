'use strict';
const $ = id => document.getElementById(id);
let sid = new URLSearchParams(location.search).get('s'), session, offset = 0, connected = false, busy = false, refreshing = false, failures = 0, pollTimer;
const key = () => `rally:${sid}`;
const identity = () => { try { return JSON.parse(localStorage.getItem(key()) || '{}'); } catch { return {}; } };
function message(text) { $('message').textContent = text; }
function el(tag, text, cls) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; }
async function request(path, data) {
  const started = Date.now();
  const headers={'Content-Type':'application/json', Authorization:`Bearer ${identity().token || ''}`};
  if(data===undefined&&session)headers['If-None-Match']=`"r${session.revision}"`;
  const response = await fetch(path, {method:data === undefined ? 'GET':'POST', headers, body:data === undefined ? undefined:JSON.stringify(data), signal:AbortSignal.timeout(10000)});
  const result = response.status===304 ? {...session,server_now:Number(response.headers.get('X-Server-Time'))} : await response.json();
  if (!response.ok && response.status!==304) throw Error(result.error || 'Request failed');
  const s = result.session || result;
  offset = s.server_now * 1000 - (started + Date.now()) / 2;
  connected = true; $('connection').textContent = 'Connected';
  return result;
}
async function action(name, data = {}) {
  if (busy) return;
  busy = true;
  try { const result = await request(`/api/sessions/${sid}/${name}`,data); if (result.token) localStorage.setItem(key(),JSON.stringify({token:result.token,player_id:result.player_id})); session=result.session; render(); message(''); return true; }
  catch(e) { message(e.message); return false; }
  finally { busy = false; scheduleRefresh(); }
}
function numeric(form) { const values=Object.fromEntries(['courts','duration','length'].map(k=>{const raw=String(form.elements.namedItem(k).value).trim();return [k,k==='length'&&raw===''?null:Number(raw)];}));values.play_format=form.elements.namedItem('play_format')?.value||session?.play_format||'doubles';return values; }
$('create').onsubmit = async e => {
  e.preventDefault(); if(busy) return; busy=true;
  try { const result=await request('/api/sessions',{name:e.target.elements.namedItem('name').value,...numeric(e.target)}); sid=result.session.id; localStorage.setItem(key(),JSON.stringify({token:result.token,player_id:result.player_id,organizer:true})); history.pushState({},'',`/?s=${encodeURIComponent(sid)}`); session=result.session; render(); }
  catch(e){message(e.message);} finally{busy=false;scheduleRefresh();}
};
$('join').onsubmit=e=>{e.preventDefault(); action('join',{name:e.target.elements.namedItem('name').value});};
$('add-player').onsubmit=async e=>{e.preventDefault();const input=e.target.elements.namedItem('name');if(await action('add-player',{name:input.value}))input.value='';};
$('court-names').onsubmit=e=>{e.preventDefault();return action('court-names',{names:Array.from($('court-name-fields').querySelectorAll('input'),input=>input.value)});};
$('settings').onsubmit=e=>{e.preventDefault();action('settings',numeric(e.target));};
$('share').onclick=async()=>{const url=location.href;try{if(navigator.share)await navigator.share({title:'Ivy League pickleball session',url});else{await navigator.clipboard.writeText(url);message('Session link copied.');}}catch(e){if(e.name!=='AbortError')message(`Share this link: ${url}`);}};
function render(){
  $('welcome').hidden=true; $('session').hidden=false;
  const me=identity(), organizer=!!me.organizer, closed=session.timer.state==='finished', manual=session.length===null, active=session.players.filter(p=>p.active), names=Object.fromEntries(session.players.map(p=>[p.id,p.name]));
  const playFormat=session.play_format||'doubles', matchSize=playFormat==='singles'?2:4;
  $('summary').textContent=`${playFormat==='singles'?'Singles':'Doubles'} · ${active.length} players · ${session.courts} courts · ${session.duration} minutes · ${manual?'Manual rounds':`${session.length}-minute rounds`}`;
  $('notice').textContent=closed?'This session has ended. The roster and schedule are read-only.':active.length<matchSize?`Waiting for at least ${matchSize} players. Share the link to fill the court.`:`Using ${Math.min(session.courts,Math.floor(active.length/matchSize))} courts. ${!manual&&session.duration%session.length ? `${session.duration%session.length} minutes reserved as buffer. `:''}Roster changes affect future rounds only. Departures during a round need a manual substitution or an early end.`;
  $('join').hidden=!!me.token||session.timer.state==='finished';
  $('round-label').textContent=closed?'SESSION ENDED':session.current<0?'READY WHEN YOU ARE':`ROUND ${session.current+1}${manual?'':` OF ${session.rounds.length}`}`;
  $('timer-state').textContent={idle:'Waiting for the organizer',running:manual?'Elapsed time · advance when everyone is ready':'On court · end the round when you’re ready',paused:'Paused',ended:'Round complete · next up below',finished:session.closed_by==='owner'?'Session ended by the app owner':session.closed_by==='organizer'?'Session ended by the organizer':'Session complete'}[session.timer.state];
  $('controls').replaceChildren();
  if(organizer){const states={idle:[['Start round','start']],ended:[['Start next round','start']],running:manual?[['Next round','next']]:[['Pause','pause'],['End round','end']],paused:[['Resume','resume'],['End round','end']],finished:[]};for(const [label,name] of states[session.timer.state]){const b=el('button',label);b.onclick=()=>action(name);$('controls').append(b);}if(!closed){const end=el('button','End session','secondary');end.onclick=()=>{if(window.confirm('End this session for everyone? The timer will stop and the session cannot be restarted.'))action('end-session');};$('controls').append(end);}}
  $('player-count').textContent=`(${active.length})`; $('roster').replaceChildren();
  for(const p of session.players){const row=el('div',undefined,'player');row.append(el('span',p.name+(p.active?'':' · left')));if(!closed&&p.active&&(organizer||p.id===me.player_id)){const b=el('button',p.id===me.player_id?'Leave':'Remove','secondary');b.onclick=()=>action('leave',{player_id:p.id});row.append(b);}else if(!closed&&!p.active&&organizer){const b=el('button','Add back','secondary');b.onclick=()=>action('add-player',{name:p.name});row.append(b);}$('roster').append(row);}
  $('add-player').hidden=closed||!organizer;
  $('court-names').hidden=closed||!organizer;
  if(!$('court-names').contains(document.activeElement)||$('court-name-fields').children.length!==session.courts){
    $('court-name-fields').replaceChildren();
    for(let i=0;i<session.courts;i++){
      const label=el('label',`Court ${i+1} name`), input=el('input');
      input.type='text';input.name=`court-${i+1}`;input.maxLength=40;
      input.placeholder=`Court ${i+1}`;input.value=session.court_names?.[i]||`Court ${i+1}`;
      label.append(input);$('court-name-fields').append(label);
    }
  }
  $('settings').hidden=closed||!organizer||session.current>=0;
  // Preserve edits while polling.
  if(!$('settings').contains(document.activeElement)){for(const k of ['courts','duration','length'])$('settings').elements.namedItem(k).value=session[k]??'';const format=$('settings').elements.namedItem('play_format');if(format)format.value=playFormat;}
  $('schedule').replaceChildren();session.rounds.forEach((r,i)=>{const card=el('article',undefined,`rotation ${i===session.current?'current':''}`);card.append(el('h3',`Round ${i+1}${i<session.current?' · completed':i===session.current?(closed?' · ended':' · current'):closed?' · not played':''}`));for(const m of r.matches){const row=el('div',undefined,'match');row.append(el('div',session.court_names?.[m.court-1]||`Court ${m.court}`,'court'),el('span',m.teams[0].map(p=>names[p]).join(' + ')),el('span','vs','versus'),el('span',m.teams[1].map(p=>names[p]).join(' + ')));card.append(row);}if(!r.matches.length)card.append(el('p','Waiting for players.'));if(r.resting.length)card.append(el('p',`Resting: ${r.resting.map(p=>names[p]).join(', ')}`,'muted'));$('schedule').append(card);});tick();
}
function tick(){
  if(!session)return;
  const timer=session.timer, now=(Date.now()+offset)/1000;
  let seconds;
  if(session.length===null){
    seconds=timer.state==='running'?Math.max(0,Math.floor(now-timer.started_at)):Math.floor(timer.elapsed||0);
    $('countdown').setAttribute('aria-label','Round elapsed time');
  }else{
    seconds=timer.remaining;
    if(timer.state==='running')seconds-=now-timer.started_at;
    seconds=Math.max(0,Math.ceil(seconds));
    $('countdown').setAttribute('aria-label','Round time remaining');
  }
  $('countdown').textContent=`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;
}

function scheduleRefresh(){
  clearTimeout(pollTimer);
  if(!sid||document.hidden||session?.timer.state==='finished')return;
  const active=session&&['running','paused'].includes(session.timer.state);
  const base=active?3000:5000;
  pollTimer=setTimeout(refresh,Math.min(30000,base*2**Math.min(failures,4)));
}
async function refresh(){
  if(!sid||busy||refreshing||document.hidden||session?.timer.state==='finished'){scheduleRefresh();return;}
  refreshing=true;
  try{
    const result=await request(`/api/sessions/${sid}`);failures=0;
    if(session&&result.revision<session.revision)return;
    const changed=!session||session.revision!==result.revision;session=result;if(changed)render();
  }catch(e){failures++;connected=false;$('connection').textContent='Disconnected · retrying';if(!session)message(e.message);}
  finally{refreshing=false;scheduleRefresh();}
}
window.addEventListener('online',()=>{failures=0;refresh();});
document.addEventListener('visibilitychange',()=>{clearTimeout(pollTimer);if(!document.hidden){failures=0;refresh();}});
window.addEventListener('popstate',()=>location.reload());
setInterval(tick,200);refresh();
