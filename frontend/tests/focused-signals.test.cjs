const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const ts=require('typescript');
const {of,Subject,Observable,throwError}=require('rxjs');

function component(api={}){
  const module={exports:{}};
  const source=fs.readFileSync(__dirname+'/../src/app/focused/focused.component.ts','utf8');
  vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,experimentalDecorators:true}}).outputText,{
    module,exports:module.exports,document:{getElementById:()=>null},
    require:name=>name==='@angular/core'?{Component:()=>x=>x,Input:()=>()=>{},Output:()=>()=>{},EventEmitter:class{},inject:()=>api}:name==='rxjs'?require('rxjs'):{}
  });
  return new module.exports.FocusedComponent();
}

test('opening Focused loads the universe without a market-wide scan',()=>{
  const c=component({fnoStocks:()=>of({stocks:[{symbol:'Z',name:'Zed',key:'z'},{symbol:'A',name:'Alpha',key:'a'}]})});
  c.ngOnInit();assert.equal(c.stocks[0].symbol,'A');assert.equal(c.data,null);assert.equal(c.selectedKey,'');
  c.query='alpha';assert.equal(c.matches.length,1);c.query='missing';assert.equal(c.matches.length,0);
  c.ngOnDestroy();
});

test('selecting a new stock cancels the old request and clears old analysis',()=>{
  let cancelled=0;const requests=[];
  const c=component({get:(url,options)=>{requests.push({url,key:options.params.instrument_key});return new Observable(()=>()=>cancelled++);}});
  c.select('stock-a');assert.equal(c.loading,true);
  c.data={stock:{symbol:'OLD'}};c.select('stock-b');
  assert.equal(cancelled,1);assert.equal(c.data,null);assert.equal(requests[1].key,'stock-b');
  assert.equal(requests[0].url,'/api/focused/structure');c.ngOnDestroy();assert.equal(cancelled,2);
});

test('all six views arrive together and errors allow retry',()=>{
  const fixture={stock:{symbol:'TEST'},views:Array.from({length:6},()=>({count:20,trend:'Higher highs / higher lows'}))};
  let failed=true;const c=component({get:()=>failed?throwError(()=>({error:{detail:'History failed'}})):of(fixture)});
  c.select('test');assert.equal(c.loading,false);assert.equal(c.error,'History failed');assert.equal(c.data,null);
  failed=false;c.refresh();assert.equal(c.error,'');assert.equal(c.data.views.length,6);
  assert.match(c.overview,/6 of 6/);assert.match(c.overview,/overlap/);
});

test('hiding or destroying Focused cancels work and activation retries an interrupted read',()=>{
  let cancelled=0,started=0;const c=component({get:()=>new Observable(()=>{started++;return()=>cancelled++;})});
  c.initialized=true;c.select('test');c.active=false;c.ngOnChanges();
  assert.equal(cancelled,1);assert.equal(c.loading,false);
  c.active=true;c.ngOnChanges();assert.equal(started,2);c.ngOnDestroy();assert.equal(cancelled,2);
});

test('late responses from a previous stock cannot overwrite the selected stock',()=>{
  const subjects=[new Subject(),new Subject()];let n=0;
  const c=component({get:()=>subjects[n++]});
  c.select('a');c.select('b');
  subjects[0].next({stock:{symbol:'A'},views:[]});assert.equal(c.data,null);
  subjects[1].next({stock:{symbol:'B'},views:[]});assert.equal(c.data.stock.symbol,'B');c.ngOnDestroy();
});
