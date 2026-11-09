const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const {Subject} = require('rxjs');

function setup(initial = null, blocked = false) {
  let saved = initial;
  const requests = [];
  const http = {get(url) { const stream=new Subject(); requests.push({url,stream}); return stream; }};
  const localStorage={getItem:()=>{if(blocked)throw Error('blocked');return saved;},setItem:(_key,value)=>{if(blocked)throw Error('blocked');saved=value;}};
  function compile(file, require) {
    const module={exports:{}};
    const js=ts.transpileModule(fs.readFileSync(__dirname+'/../src/app/learning/'+file,'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,experimentalDecorators:true}}).outputText;
    vm.runInNewContext(js,{module,exports:module.exports,localStorage,setTimeout,clearTimeout,require});return module.exports;
  }
  const types=compile('learning.types.ts',()=>({}));
  const module=compile('learning.component.ts',name=>name.includes('learning.types')?types:name==='@angular/core'?{Component:()=>x=>x,ViewChild:()=>()=>{},ViewEncapsulation:{None:2},inject:()=>http}:{});
  return {c:new module.LearningComponent(),types,requests,saved:()=>saved};
}

const chapter=(id,title,text,category='Risk')=>({id,title,searchText:text,category,headings:[],number:1,words:100});
const chapters=[chapter('risk-position-sizing','Risk & position sizing','Budget and stop distance'),chapter('options-3-the-greeks','Options Greeks','Theta and volatility','Options')];
const manifest={chapters};

test('loads static chapters, cancels superseded requests and searches the full text',()=>{
  const {c,requests}=setup();c.ngOnInit();assert.equal(requests[0].url,'assets/learning/manifest.json');
  requests[0].stream.next(manifest);assert.equal(requests[1].url,'assets/learning/risk-position-sizing.json');
  c.search='theta';assert.equal(c.filteredChapters[0].id,'options-3-the-greeks');
  c.openChapter('options-3-the-greeks');assert.equal(requests[1].stream.observers.length,0);
  requests[2].stream.next({id:'options-3-the-greeks',html:'<p>Theta</p>',headings:[]});
  assert.equal(c.content.id,'options-3-the-greeks');
  c.ngOnDestroy();assert.equal(requests[2].stream.observers.length,0);
});

test('reading progress, checks and notes survive reopening and reset only clears checks',()=>{
  const s=setup();s.c.ngOnInit();s.requests[0].stream.next(manifest);
  s.c.toggleRead();s.c.check('size',true);s.c.setNotes('My plan');s.c.changeView('checklist');
  const next=setup(s.saved());next.c.ngOnInit();next.requests[0].stream.next(manifest);
  assert.equal(next.c.read.has('risk-position-sizing'),true);assert.equal(next.c.checked.has('size'),true);
  assert.equal(next.c.notes,'My plan');assert.equal(next.c.view,'checklist');
  next.c.resetChecks();assert.equal(next.c.checked.size,0);assert.equal(next.c.notes,'My plan');assert.equal(next.c.read.size,1);
  s.c.ngOnDestroy();next.c.ngOnDestroy();
});

test('stock checklist excludes option-only checks and missing requirements never imply a trade signal',()=>{
  const {c}=setup();const all=c.checkCount;const required=c.requiredLeft;
  c.setOptions(false);assert.ok(c.checkCount<all);assert.ok(c.requiredLeft<required);
  for(const group of c.checklistGroups)for(const item of group.items)c.check(item.id,true);
  assert.equal(c.requiredLeft,0);assert.equal(c.completedChecks,c.checkCount);
});

test('chapter errors and blocked browser storage remain usable',()=>{
  const {c,requests}=setup(null,true);c.ngOnInit();requests[0].stream.next(manifest);
  requests[1].stream.error(new Error('missing'));assert.match(c.chapterError,/retry/i);
  c.check('size',true);assert.equal(c.checked.has('size'),true);assert.equal(c.storageError,true);c.ngOnDestroy();
});

test('every checklist source points to an imported chapter and saved navigation gains Learning',()=>{
  const {types}=setup();
  const actual=JSON.parse(fs.readFileSync(__dirname+'/../public/assets/learning/manifest.json','utf8'));
  const ids=new Set(actual.chapters.map(c=>c.id));
  for(const group of types.TRADING_CHECKLIST)for(const item of group.items)assert.equal(ids.has(item.chapter),true,item.id);
  const config=JSON.parse(fs.readFileSync(__dirname+'/../angular.json','utf8'));
  assert.ok(config.projects['market-desk'].architect.build.options.assets.some(a=>a.input==='public'));
});
