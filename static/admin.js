'use strict';
const form=document.getElementById('owner-end'), message=document.getElementById('owner-message'), link=document.getElementById('session-link');
let pending=false;
form.onsubmit=async event=>{
  event.preventDefault();if(pending)return;
  link.hidden=true;message.textContent='';
  const raw=form.elements.namedItem('session').value.trim();
  let sid=raw;
  try{if(raw.includes('://'))sid=new URL(raw).searchParams.get('s');}catch{sid=null;}
  if(!sid||!/^[A-Za-z0-9_-]{1,80}$/.test(sid)){message.textContent='Enter a valid session link or ID.';return;}
  if(!window.confirm('End this session for everyone? It will become read-only and cannot be restarted.'))return;
  pending=true;const button=form.querySelector('button');button.disabled=true;
  try{
    const key=form.elements.namedItem('owner-key');
    const secret=key.value;key.value='';
    const response=await fetch(`/api/admin/sessions/${encodeURIComponent(sid)}/end`,{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${secret}`},body:'{}',signal:AbortSignal.timeout(15000)});
    const result=await response.json();
    if(!response.ok)throw Error(result.error||'Could not end session.');
    message.textContent='Session ended. The timer is stopped and further changes are blocked.';
    link.href=`/?s=${encodeURIComponent(sid)}`;link.hidden=false;
  }catch(error){message.textContent=error.message+' If the request timed out, check the session before retrying.';}
  finally{pending=false;button.disabled=false;}
};
