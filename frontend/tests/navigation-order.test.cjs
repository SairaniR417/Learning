const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const ts=require('typescript');

function setup(initial=null,blocked=false){
  let saved=initial;
  const localStorage={getItem:()=>{if(blocked)throw Error('blocked');return saved;},setItem:(_key,value)=>{if(blocked)throw Error('blocked');saved=value;}};
  function compile(file,require){
    const module={exports:{}};
    const js=ts.transpileModule(fs.readFileSync(__dirname+'/../src/app/'+file,'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,experimentalDecorators:true}}).outputText;
    vm.runInNewContext(js,{module,exports:module.exports,localStorage,require});return module.exports;
  }
  const order=compile('navigation-order.ts',()=>({}));
  const app=compile('app.component.ts',name=>name.includes('navigation-order')?order:name==='@angular/core'?{Component:()=>x=>x,inject:()=>({})}:name.includes('backend-url')?{backendUrl:x=>x}:{});
  return {order,component:new app.AppComponent(),saved:()=>saved};
}

test('moves Scanner first, persists reload order and leaves active page unchanged',()=>{
  const s=setup();s.component.page='Watchlist';s.component.moveTab('Option Chains',0);
  assert.equal(s.component.pages[0],'Option Chains');assert.equal(s.component.page,'Watchlist');
  assert.equal(setup(s.saved()).component.pages[0],'Option Chains');
});

test('saved tabs are deduplicated, obsolete values ignored and missing tabs appended',()=>{
  const s=setup(JSON.stringify(['Option Chains','Option Chains','removed',12]));
  assert.equal(s.component.pages[0],'Option Chains');assert.equal(s.component.pages.length,s.order.DEFAULT_PAGES.length);
  assert.equal(new Set(s.component.pages).size,s.component.pages.length);
  for(const value of ['invalid','{}','null'])assert.equal(setup(value).component.pages[0],'Overview');
});

test('keyboard and drop reorder tabs; external drops and invalid positions do nothing',()=>{
  const s=setup();let prevented=0;
  s.component.tabKeydown({altKey:true,key:'ArrowLeft',preventDefault:()=>prevented++},'Market Scanner');
  assert.equal(prevented,1);assert.equal(s.component.pages[0],'Market Scanner');
  const before=JSON.stringify(s.component.pages);
  s.component.dropTab({preventDefault:()=>{}},'Overview');assert.equal(JSON.stringify(s.component.pages),before);
  s.component.startTabDrag({dataTransfer:{setData:()=>{}}},'Option Chains');
  s.component.dropTab({preventDefault:()=>{}},'Market Scanner');assert.equal(s.component.pages[0],'Option Chains');
  assert.equal(s.component.draggedTab,null);
  s.component.moveTab('Option Chains',-1);assert.equal(s.component.pages[0],'Option Chains');
});

test('blocked storage still permits arranging tabs',()=>{
  const s=setup(null,true);s.component.moveTab('Option Chains',0);
  assert.equal(s.component.pages[0],'Option Chains');
});
