const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/app.js'),'utf8');
for(const value of ['null','[]','bad json'])test('invalid saved preferences recover: '+value,()=>{const ctx={localStorage:{getItem:()=>value}};vm.createContext(ctx);vm.runInContext(source.slice(source.indexOf('function readPrefs()'),source.indexOf('function savePrefs(')),ctx);assert.equal(JSON.stringify(ctx.readPrefs()),'{}');});
test('busy state locks and restores quote, basis and source controls',()=>{const elements={};const control={disabled:false,matches:()=>false};const quote={disabled:false,matches:()=>true};const basis={dataset:{basis:'MID'}};const ctx={closedSession:()=>false,state:{record:{source:'FUTU',input:{}},selected:new Set()},$:key=>elements[key]??=( {} ),$$:selector=>selector.includes('data-source')?[control,quote]:selector.includes('data-basis')?[basis]:[]};vm.createContext(ctx);vm.runInContext(source.slice(source.indexOf('function busy('),source.indexOf('function source(')),ctx);ctx.busy(true);assert.equal(control.disabled,true);assert.equal(quote.disabled,true);assert.equal(basis.disabled,true);ctx.busy(false);assert.equal(control.disabled,false);assert.equal(quote.disabled,false);assert.equal(basis.disabled,false);});

const editor=import('../app/static/editor-model.mjs');
function importedRow(){return {strike:'275',issues:['来自导入的合约校验问题'],call:{code:'US.TEST',last:7.59,bid:7.5,ask:7.7,adjusted:true,multiplier:'10',exercise:'EUROPEAN',currency:'USD',lastAt:'2026-10-30T20:00:00Z',bookAt:'2026-10-30T20:00:00Z',updatedAt:'2026-10-30T20:00:00Z'},put:{last:3.67,bid:null,ask:null}};}
test('unchanged import and saved draft preserve contract restrictions and timestamps',async()=>{const {toDraft,fromDraft}=await editor;const d=toDraft(importedRow(),{symbol:'GOOG',expiration:'2026-11-06'});const saved=JSON.parse(JSON.stringify(d));assert.deepEqual(fromDraft(saved.values,saved.original),d.original);assert.equal(saved.original.call.underlying,'GOOG');assert.equal(saved.original.call.expiration,'2026-11-06');});
test('editing LAST invalidates only its event timestamp and snapshot timestamp',async()=>{const {toDraft,fromDraft}=await editor;const d=toDraft(importedRow(),{symbol:'GOOG',expiration:'2026-11-06'});d.values.call_last='8';const row=fromDraft(d.values,d.original);assert.equal(row.call.lastAt,null);assert.equal(row.call.updatedAt,null);assert.equal(row.call.bookAt,d.original.call.bookAt);assert.equal(row.call.adjusted,true);assert.equal(row.call.multiplier,'10');assert.deepEqual(row.issues,d.original.issues);});
test('editing bid invalidates book time without erasing LAST timestamp',async()=>{const {toDraft,fromDraft}=await editor;const d=toDraft(importedRow(),{symbol:'GOOG',expiration:'2026-11-06'});d.values.call_bid='7';const row=fromDraft(d.values,d.original);assert.equal(row.call.bookAt,null);assert.equal(row.call.lastAt,d.original.call.lastAt);});
test('cannot relabel an existing contract by editing strike',async()=>{const {toDraft,fromDraft}=await editor;const d=toDraft(importedRow(),{symbol:'GOOG',expiration:'2026-11-06'});d.values.strike='280';assert.throws(()=>fromDraft(d.values,d.original),/行权价/);});
test('clearing imported prices does not clear contract restrictions',async()=>{const {toDraft,fromDraft}=await editor;const d=toDraft(importedRow(),{symbol:'GOOG',expiration:'2026-11-06'});for(const k of ['last','bid','ask'])d.values['call_'+k]='';const row=fromDraft(d.values,d.original);assert.equal(row.call.adjusted,true);assert.equal(row.call.last,null);});
test('new blank rows omitted, zero retained, missing put stays missing',async()=>{const {fromDraft}=await editor;assert.equal(fromDraft({}),null);const row=fromDraft({strike:'100',call_last:'0'});assert.equal(row.call.last,0);assert.equal(row.put,null);});

test('opening clears previous market results even if refresh is paused and the API is offline',()=>{
 const cleared=[];
 const state={record:{source:'FUTU',expiresAt:'2026-11-30T14:30:00Z'},timer:null,comparison:{},selected:new Set(['100']),lastSuccess:'old',epoch:1};
 const ctx={state,Date:{now:()=>Date.parse('2026-11-30T14:30:00Z'),parse:Date.parse},
  $:id=>({replaceChildren:()=>cleared.push(id)}),message(){},render(){},refreshLabel(){}};
 vm.createContext(ctx);
 vm.runInContext(source.slice(source.indexOf('function expireDisplayed()'),source.indexOf('async function syncSession()')),ctx);
 ctx.expireDisplayed();
 assert.equal(state.record,null);assert.equal(state.comparison,null);assert.equal(state.lastSuccess,null);
 assert.equal(state.epoch,2);assert.ok(cleared.includes('#quote-rows'));assert.ok(cleared.includes('#comparison'));
});
