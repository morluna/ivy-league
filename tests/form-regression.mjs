// Run with: node tests/form-regression.mjs
// Exercises the actual UI handlers with the native collection `length` collision.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

function node() {
  return {value: '', textContent: '', hidden: false, append() {}, replaceChildren() {}, contains() {return false;}};
}
function form(values) {
  const inputs = Object.fromEntries(Object.entries(values).map(([k,v]) => [k,{value:String(v)}]));
  const elements = {namedItem(name) {return inputs[name];}};
  Object.defineProperty(elements,'length',{value:Object.keys(inputs).length,writable:false});
  for (const [k,v] of Object.entries(inputs)) if(k !== 'length') elements[k] = v;
  return {...node(), elements};
}
const nodes = new Map();
const get = id => {if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
nodes.set('create',form({name:'Host',courts:2,duration:120,length:10}));
nodes.set('settings',form({courts:2,duration:120,length:10}));
const store = new Map(), calls=[];
let snapshot={id:'test-session',server_now:Date.now()/1000,revision:1,courts:2,duration:120,length:10,current:-1,timer:{state:'idle',remaining:600},players:[{id:'host',name:'Host',active:true}],rounds:[]};
const context = vm.createContext({
  URLSearchParams, AbortSignal, console,
  location:{search:'',href:'http://localhost:8000/',reload(){}},history:{pushState(){}},
  localStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)},
  document:{getElementById:get,createElement:node,addEventListener(){},activeElement:null},
  window:{addEventListener(){}},setInterval(){},navigator:{},
  fetch:async(path,options)=>{
    const body=JSON.parse(options.body);calls.push({path,body});
    if(path.endsWith('/settings'))snapshot={...snapshot,...body,revision:2};
    return {ok:true,json:async()=>({session:snapshot,token:'test-token',player_id:'host'})};
  }
});
vm.runInContext(await readFile(new URL('../static/app.js',import.meta.url),'utf8'),context);
await get('create').onsubmit({preventDefault(){},target:get('create')});
assert.equal(calls.length,1);
assert.deepEqual(calls[0].body,{name:'Host',courts:2,duration:120,length:10});
assert.equal(get('message').textContent,'');
assert.equal(get('session').hidden,false);
assert.equal(get('settings').elements.namedItem('length').value,10);
get('settings').elements.namedItem('length').value='15';
await vm.runInContext("action('settings',numeric(document.getElementById('settings')))",context);
assert.deepEqual(calls[1].body,{courts:2,duration:120,length:15});
assert.equal(get('message').textContent,'');
assert.equal(get('settings').elements.length,3);
console.log('PASS: session creation and settings use named fields despite collection.length.');
