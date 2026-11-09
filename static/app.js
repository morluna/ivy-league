'use strict';
const $ = id => document.getElementById(id);
let sid = new URLSearchParams(location.search).get('s'), session, offset = 0, connected = false, busy = false;
const key = () => `rally:${sid}`;
const identity = () => { try { return JSON.parse(localStorage.getItem(key()) || '{}'); } catch { return {}; } };
function message(text) { $('message').textContent = text; }
function el(tag, text, cls) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; }
async function request(path, data) {
  const started = Date.now();
  const response = await fetch(path, {method:data === undefined ? 'GET':'POST', headers:{'Content-Type':'application/json', Authorization:`Bearer ${identity().token || ''}`}, body:data === undefined ? undefined:JSON.stringify(data), signal:AbortSignal.timeout(10000)});
  const result = await response.json();
  if (!response.ok) throw Error(result.error || 'Request failed');
  const s = result.session || result;
  offset = s.server_now * 1000 - (started + Date.now()) / 2;
  connected = true; $('connection').textContent = 'Connected';
  return result;
}
async function action(name, data = {}) {
  if (busy) return;
  busy = true;
  try { const result = await request(`/api/sessions/${sid}/${name}`,data); if (result.token) localStorage.setItem(key(),JSON.stringify({token:result.token,player_id:result.player_id})); session=result.session; render(); message(''); }
  catch(e) { message(e.message); }
  finally { busy = false; }
}
function numeric(form) { return Object.fromEntries(['courts','duration','length'].map(k=>[k,Number(form.elements.namedItem(k).value)])); }
$('create').onsubmit = async e => {
  e.preventDefault(); if(busy) return; busy=true;
  try { const result=await request('/api/sessions',{name:e.target.elements.namedItem('name').value,...numeric(e.target)}); sid=result.session.id; localStorage.setItem(key(),JSON.stringify({token:result.token,player_id:result.player_id,organizer:true})); history.pushState({},'',`/?s=${encodeURIComponent(sid)}`); session=result.session; render(); }
  catch(e){message(e.message);} finally{busy=false;}
};
$('join').onsubmit=e=>{e.preventDefault(); action('join',{name:e.target.elements.namedItem('name').value});};
$('settings').onsubmit=e=>{e.preventDefault();action('settings',numeric(e.target));};
$('share').onclick=async()=>{const url=location.href;try{if(navigator.share)await navigator.share({title:'Join our pickleball session',url});else{await navigator.clipboard.writeText(url);message('Session link copied.');}}catch(e){if(e.name!=='AbortError')message(`Share this link: ${url}`);}};
function render(){
  $('welcome').hidden=true; $('session').hidden=false;
  const me=identity(), organizer=!!me.organizer, closed=session.timer.state==='finished', active=session.players.filter(p=>p.active), names=Object.fromEntries(session.players.map(p=>[p.id,p.name]));
  $('summary').textContent=`${active.length} players · ${session.courts} courts · ${session.duration} minutes · ${session.length}-minute rounds`;
  $('notice').textContent=closed?'This session has ended. The roster and schedule are read-only.':active.length<4?'Waiting for at least four players. Share the link to fill the court.':`Using ${Math.min(session.courts,Math.floor(active.length/4))} courts. ${session.duration%session.length ? `${session.duration%session.length} minutes reserved as buffer. `:''}Roster changes affect future rounds only. Departures during a round need a manual substitution or an early end.`;
  $('join').hidden=!!me.token||session.timer.state==='finished';
  $('round-label').textContent=closed?'SESSION ENDED':session.current<0?'READY WHEN YOU ARE':`ROUND ${session.current+1} OF ${session.rounds.length}`;
  $('timer-state').textContent={idle:'Waiting for the organizer',running:'On court · end the round when you’re ready',paused:'Paused',ended:'Round complete · next up below',finished:session.closed_by==='owner'?'Session ended by the app owner':session.closed_by==='organizer'?'Session ended by the organizer':'Session complete'}[session.timer.state];
  $('controls').replaceChildren();
  if(organizer){const states={idle:[['Start round','start']],ended:[['Start next round','start']],running:[['Pause','pause'],['End round','end']],paused:[['Resume','resume'],['End round','end']],finished:[]};for(const [label,name] of states[session.timer.state]){const b=el('button',label);b.onclick=()=>action(name);$('controls').append(b);}if(!closed){const end=el('button','End session','secondary');end.onclick=()=>{if(window.confirm('End this session for everyone? The timer will stop and the session cannot be restarted.'))action('end-session');};$('controls').append(end);}}
  $('player-count').textContent=`(${active.length})`; $('roster').replaceChildren();
  for(const p of session.players){const row=el('div',undefined,'player');row.append(el('span',p.name+(p.active?'':' · left')));if(!closed&&p.active&&(organizer||p.id===me.player_id)){const b=el('button',p.id===me.player_id?'Leave':'Remove','secondary');b.onclick=()=>action('leave',{player_id:p.id});row.append(b);}$('roster').append(row);}
  $('settings').hidden=closed||!organizer||session.current>=0;
  // Preserve edits while polling.
  if(!$('settings').contains(document.activeElement))for(const k of ['courts','duration','length'])$('settings').elements.namedItem(k).value=session[k];
  $('schedule').replaceChildren();session.rounds.forEach((r,i)=>{const card=el('article',undefined,`rotation ${i===session.current?'current':''}`);card.append(el('h3',`Round ${i+1}${i<session.current?' · completed':i===session.current?(closed?' · ended':' · current'):closed?' · not played':''}`));for(const m of r.matches){const row=el('div',undefined,'match');row.append(el('div',`COURT ${m.court}`,'court'),el('span',m.teams[0].map(p=>names[p]).join(' + ')),el('span','vs','versus'),el('span',m.teams[1].map(p=>names[p]).join(' + ')));card.append(row);}if(!r.matches.length)card.append(el('p','Waiting for players.'));if(r.resting.length)card.append(el('p',`Resting: ${r.resting.map(p=>names[p]).join(', ')}`,'muted'));$('schedule').append(card);});tick();
}
function tick(){if(!session)return;let seconds=session.timer.remaining;if(session.timer.state==='running')seconds-=(Date.now()+offset)/1000-session.timer.started_at;seconds=Math.max(0,Math.ceil(seconds));$('countdown').textContent=`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;}
async function refresh(){if(!sid||busy)return;try{const result=await request(`/api/sessions/${sid}`);if(session&&result.revision<session.revision)return;const changed=!session||session.revision!==result.revision;session=result;if(changed)render();}catch(e){connected=false;$('connection').textContent='Disconnected · retrying';if(!session)message(e.message);}}
window.addEventListener('online',refresh);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});window.addEventListener('popstate',()=>location.reload());setInterval(refresh,1500);setInterval(tick,200);refresh();
