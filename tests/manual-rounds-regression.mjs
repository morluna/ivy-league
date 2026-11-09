import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
function node(){return {textContent:'',hidden:false,children:[],setAttribute(){},append(...v){this.children.push(...v)},replaceChildren(...v){this.children=v},contains(){return false}};}
function form(values){const inputs=Object.fromEntries(Object.entries(values).map(([k,v])=>[k,{value:String(v)}]));return {...node(),elements:{namedItem:k=>inputs[k]}};}
const nodes=new Map([['create',form({name:'Host',courts:2,duration:120,length:''})],['settings',form({courts:2,duration:120,length:''})],['add-player',form({name:''})]]);
const get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id)};
const store=new Map();let now=1000000,snapshot,calls=[];
const context=vm.createContext({URLSearchParams,AbortSignal,Date:{now:()=>now},document:{getElementById:get,createElement:node,addEventListener(){},hidden:false},location:{search:''},history:{pushState(){}},navigator:{},window:{addEventListener(){},confirm:()=>true},localStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)},setTimeout(){},clearTimeout(){},setInterval(){},fetch:async(path,options)=>{
 const data=JSON.parse(options.body);calls.push({path,data});
 if(path==='/api/sessions')snapshot={...data,id:'manual',revision:1,current:-1,rounds:[],players:[{id:'host',name:'Host',active:true}],timer:{state:'idle',remaining:null,started_at:null}};
 if(path.endsWith('/start')||path.endsWith('/next'))snapshot={...snapshot,current:snapshot.current+1,revision:snapshot.revision+1,timer:{state:'running',started_at:now/1000,remaining:null,elapsed:0}};
 if(path.endsWith('/end-session'))snapshot={...snapshot,revision:snapshot.revision+1,closed_by:'organizer',timer:{state:'finished',started_at:null,remaining:0,elapsed:now/1000-snapshot.timer.started_at}};
 return {ok:true,json:async()=>path==='/api/sessions'?{session:{...snapshot,server_now:now/1000},token:'organizer',player_id:'host'}:{session:{...snapshot,server_now:now/1000}}};
}});
const run=code=>vm.runInContext(code,context);
run(await readFile(new URL('../static/app.js',import.meta.url),'utf8'));
await get('create').onsubmit({preventDefault(){},target:get('create')});
assert.equal(calls[0].data.length,null);
assert.equal(get('settings').elements.namedItem('length').value,'');
assert(get('summary').textContent.includes('Manual rounds'));
assert.equal(get('countdown').textContent,'00:00');
await run("action('start')");now+=65000;run('tick()');
assert.equal(get('countdown').textContent,'01:05');
assert(!get('controls').children.some(b=>b.textContent==='Pause'));
const next=get('controls').children.find(b=>b.textContent==='Next round');assert(next);
await next.onclick();assert.equal(get('countdown').textContent,'00:00');
assert.equal(get('round-label').textContent,'ROUND 2');
now+=22000;run('tick()');assert.equal(get('countdown').textContent,'00:22');
await run("action('end-session')");now+=500000;run('tick()');
assert.equal(get('countdown').textContent,'00:22');
assert.equal(get('round-label').textContent,'SESSION ENDED');
console.log('PASS: optional minutes, synchronized count-up display, Next round reset, and stopped elapsed time after closure.');
