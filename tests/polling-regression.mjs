import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
function node(){return {value:'',textContent:'',children:[],setAttribute(){},append(...items){this.children.push(...items)},replaceChildren(...items){this.children=items},contains(){return false}};}
const nodes=new Map();
const get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id)};
for(const [id,values] of Object.entries({create:{name:'Host',courts:2,duration:120,length:10},settings:{courts:2,duration:120,length:10},'add-player':{name:''}})){
 const inputs=Object.fromEntries(Object.entries(values).map(([k,v])=>[k,{value:String(v)}]));
 nodes.set(id,{...node(),elements:{namedItem:k=>inputs[k]}});
}
const timers=new Map(),events={},store=new Map();let timerId=0,calls=0;
const snapshot={id:'test',revision:1,server_now:1000,players:[{id:'host',name:'Host',active:true}],rounds:[],current:-1,courts:2,duration:120,length:10,timer:{state:'idle',remaining:600,started_at:null}};
const document={hidden:false,getElementById:get,createElement:node,addEventListener:(name,fn)=>events[name]=fn};
const context=vm.createContext({URLSearchParams,AbortSignal,document,location:{search:''},history:{pushState(){}},navigator:{},window:{addEventListener:(name,fn)=>events[name]=fn},localStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)},setInterval:(fn,delay)=>assert.equal(delay,200),setTimeout:(fn,delay)=>{timers.set(++timerId,{fn,delay});return timerId},clearTimeout:id=>timers.delete(id),fetch:async()=>{calls++;return {ok:true,status:200,json:async()=>({session:snapshot,token:'organizer',player_id:'host'})}}});
const run=code=>vm.runInContext(code,context);
const delay=()=>{assert.equal(timers.size,1);return [...timers.values()][0].delay};
vm.runInContext(await readFile(new URL('../static/app.js',import.meta.url),'utf8'),context);
await get('create').onsubmit({preventDefault(){},target:get('create')});
assert.equal(delay(),5000);
run("session={...session,timer:{state:'running',remaining:600,started_at:1000}};scheduleRefresh()");
assert.equal(delay(),3000);
context.fetch=async(path,options)=>{calls++;assert.equal(options.headers['If-None-Match'],'"r1"');return {ok:false,status:304,headers:{get:()=>String(1001)},json(){throw Error('304 must not parse a body')}}};
await run('refresh()');assert.equal(delay(),3000);assert(Number.isFinite(run('offset')));
const before=calls;document.hidden=true;events.visibilitychange();await run('refresh()');
assert.equal(calls,before);assert.equal(timers.size,0);
document.hidden=false;events.visibilitychange();await new Promise(resolve=>setImmediate(resolve));
assert.equal(calls,before+1);assert.equal(delay(),3000);
let resolveFetch;context.fetch=()=>{calls++;return new Promise(resolve=>resolveFetch=resolve)};
const first=run('refresh()');const second=run('refresh()');const concurrentCalls=calls;
resolveFetch({ok:false,status:304,headers:{get:()=>String(1002)}});await Promise.all([first,second]);
assert.equal(calls,concurrentCalls);
context.fetch=async()=>{throw Error('offline')};
for(const expected of [6000,12000,24000,30000]){await run('refresh()');assert.equal(delay(),expected)}
context.fetch=async()=>({ok:false,status:304,headers:{get:()=>String(1003)}});
events.online();await new Promise(resolve=>setImmediate(resolve));assert.equal(delay(),3000);
run("session.timer.state='finished';scheduleRefresh()");assert.equal(timers.size,0);
const endedCalls=calls;await run('refresh()');assert.equal(calls,endedCalls);assert.equal(timers.size,0);
console.log('PASS: adaptive polling, hidden/closed-session silence, 304 responses, no overlap, backoff, and reconnect.');
