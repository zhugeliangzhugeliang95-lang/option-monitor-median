import {fields,toDraft,fromDraft} from './editor-model.mjs';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const REFRESH_MS=10000;
const state={nextRefresh:null,connection:null,lastSuccess:null,source:'futu',basis:'LAST',record:null,selected:new Set(),comparison:null,busy:false,epoch:0,timer:null};
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=(v,d=3)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d}):'—';
const num=v=>v.trim()===''?null:Number(v);
const when=v=>v?new Date(v).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})+' 北京时间':'未提供';
const originLabels={FUTU:'FUTU / API 快照',MANUAL:'MANUAL / 人工数据'};
const basisLabel=()=>state.basis==='LAST'?'最新成交价':'买卖中间价';
function message(text=''){$('#message').textContent=text;$('#message').hidden=!text;}
function errorText(data){const detail=data?.detail;if(Array.isArray(detail))return detail.map(x=>{const field=x.loc?.filter(y=>y!=='body').join('.');return (field?field+'：':'')+String(x.msg).replace(/^Value error, /,'');}).join('；');return typeof detail==='string'?detail:'请求失败，请重试。';}
async function api(path,body){const r=await fetch(new URL('api'+path,document.baseURI),{method:body===undefined?'GET':'POST',signal:AbortSignal.timeout(45000),headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});let data;try{data=await r.json();}catch{throw Error('服务没有返回有效结果，请确认程序仍在运行。');}if(!r.ok){const error=Error(errorText(data));error.status=r.status;throw error;}return data;}
function busy(value){state.busy=value;$$('[data-source], #quote-rows input, #open-editor, #file').forEach(b=>b.disabled=value||(b.matches('#quote-rows input')&&!state.record?.input));$('#fetch-live').disabled=value;$('#fetch-live').textContent=value?'正在读取报价…':closedSession()?'手动获取富途快照':'获取富途报价 ↗';$('#calculate').disabled=value;$('#check-connection').disabled=value;$$('[data-ticker]').forEach(b=>b.disabled=value);$$('[data-basis]').forEach(b=>b.disabled=value);$('#compare').disabled=value||state.selected.size!==3||!state.record?.input;}
function source(name,clear=true){state.epoch++;state.source=name;stopAuto(false);message();if(clear){state.record=null;state.comparison=null;state.selected.clear();render();}$$('[data-source]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.source===name)));for(const n of ['futu','manual'])$('#'+n+'-controls').hidden=n!==name;}
function apply(record,preserve=false){
 const old=state.record,keep=preserve&&old?.report.symbol===record.report.symbol&&old?.report.expiration===record.report.expiration;
 const oldSelection=new Set([...state.selected].map(Number));
 state.record=record;state.comparison=null;if(record.source==='MANUAL')populateManual(record);
 if(!keep)state.basis=preferredBasis();
 if(!keep)showView('ranking');
 const rows=record.report.modes[state.basis].rows;
 if(record.report.center!=null){
  state.selected=new Set(rows.map(r=>r.strike));
  render();
  return;
 }
 const surviving=rows.filter(r=>oldSelection.has(Number(r.strike))).map(r=>r.strike);
 const center=rows.findIndex(r=>Number(r.strike)===Number(record.report.center));
 const start=Math.max(0,Math.min(rows.length-3,(center>=0?center:Math.floor(rows.length/2))-1));
 state.selected=new Set(record.input?(keep&&surviving.length===oldSelection.size?surviving:rows.slice(start,start+3).map(r=>r.strike)):[]);
 render();
}
function readPrefs(){try{const p=JSON.parse(localStorage.getItem('strike-lab-preferences')||'{}');return p&&typeof p==='object'&&!Array.isArray(p)?p:{};}catch{return {};}}
function savePrefs(patch={}){try{localStorage.setItem('strike-lab-preferences',JSON.stringify({...readPrefs(),...patch}));}catch{}}
function preferredBasis(){return readPrefs().basis==='MID'?'MID':'LAST';}
const marketNames={PRE_MARKET_BEGIN:'美股盘前',PRE_MARKET_END:'美股盘前结束',MORNING:'美股常规交易时段',AFTERNOON:'美股常规交易时段',CLOSED:'美股已收盘',AFTER_HOURS_BEGIN:'美股盘后',AFTER_HOURS_END:'美股盘后结束',NIGHT_OPEN:'美股夜盘',NIGHT_END:'美股夜盘结束',REST:'美股休市',NONE:'美股休市/未定'};
function connectionView(info,error){state.connection=info||null;$('#connection-title').textContent=error?'行情连接未就绪':info?.quoteLoggedIn?'OpenD 行情已连接':'OpenD 尚未登录行情';$('#connection-detail').textContent=error||`正股权限 ${info.stockRight} · 期权权限 ${info.optionRight}\n${marketNames[info.marketUS]||info.marketUS} · ${when(info.checkedAt)}`;}
async function checkConnection(){if(state.busy)return;busy(true);$('#check-connection').disabled=true;try{connectionView(await api('/futu/status'));}catch(e){connectionView(null,e.message);}finally{busy(false);}}
async function updateComparison(epoch=state.epoch){
 if(!state.record?.input||state.record.report.center!=null||state.selected.size!==3)return;
 const id=state.record.id,basis=state.basis,strikes=[...state.selected];
 const r=await api(`/studies/${id}/compare`,{basis,strikes});
 if(epoch===state.epoch&&id===state.record?.id&&basis===state.basis){state.comparison=r;renderComparison();}
}
let marketSession=null, sessionRequest=null, retrySessionAt=0;
function boundaryAt(session){
 return session?Date.parse(session.isOpen?session.closedAt:session.expiresAt):0;
}
function expireDisplayed(){
 const item=state.record;
 if(item?.source!=='FUTU'||!item.expiresAt||Date.now()<Date.parse(item.expiresAt))return;
 state.epoch++;state.record=null;state.comparison=null;state.selected.clear();state.lastSuccess=null;
 for(const id of ['quote-rows','comparison','provenance','freshness','quote-age','method-content','study-time','study-symbol','expiry-badge','selection-note','selection-count'])$('#'+id).replaceChildren();
 message();render();refreshLabel();
}
async function syncSession(){
 expireDisplayed();
 if(sessionRequest)return sessionRequest;
 sessionRequest=(async()=>{
  const session=await api('/market-session');
  const previous=marketSession;
  marketSession=session;
  retrySessionAt=0;
  if(state.source==='futu'&&!session.isOpen){
   const epoch=state.epoch;
   if(session.latestId&&session.latestId!==state.record?.id){
    const retained=await api('/studies/'+session.latestId+'/export');
    if(epoch===state.epoch&&state.source==='futu'&&Date.now()<Date.parse(retained.expiresAt)){
     apply(retained,true);state.lastSuccess=retained.receivedAt;
    }
   }
   if(state.record?.source==='FUTU'){$('#symbol').value=state.record.report.symbol;quoteAge();}
  }
  if(session.isOpen&&previous&&!previous.isOpen)state.nextRefresh=Date.now();
  refreshLabel();busy(state.busy);
  return session;
 })().catch(error=>{retrySessionAt=Date.now()+10000;throw error;}).finally(()=>{sessionRequest=null;});
 return sessionRequest;
}
function closedSession(){return marketSession&&!marketSession.isOpen&&Date.now()<boundaryAt(marketSession);}
function sessionTick(){
 expireDisplayed();
 if(!document.hidden&&Date.now()>=retrySessionAt&&Date.now()>=boundaryAt(marketSession)&&!sessionRequest)
  syncSession().catch(e=>{if(state.source==='futu')message(e.message);});
}
async function fetchLive(manual=false){
 if(state.busy||state.source!=='futu')return;
 const symbol=(manual?$('#symbol').value:(readPrefs().symbol||'SPY')).trim().toUpperCase();
 if(Date.now()>=boundaryAt(marketSession)){
  try{await syncSession();}catch(e){message(e.message);return;}
 }
 if((closedSession()&&!manual)||state.busy||state.source!=='futu')return;
 if(!symbol){message('请输入美股或 ETF 代码。');return;}
 if(manual){$('#symbol').value=symbol;savePrefs({symbol});}
 if(state.timer)state.nextRefresh=Date.now()+REFRESH_MS;
 const epoch=++state.epoch;busy(true);message();
 try{const r=await api('/futu',{symbol,manual});
  if(epoch===state.epoch&&Date.now()<Date.parse(r.expiresAt)){apply(r,true);if(r.connection)connectionView(r.connection);state.lastSuccess=r.receivedAt;await updateComparison(epoch);}
 }catch(e){if(epoch===state.epoch){if(e.status===503||e.status===504)connectionView(null,e.message);message((e.name==='TimeoutError'?'请求超时，请确认本机服务正常。':e.message)+(state.record?' 下方保留上一次研究快照及原时间。':'')+(state.timer&&!closedSession()?' 将在下一刷新周期重试。':''));}}
 finally{busy(false);refreshLabel();}
}
function startAuto(immediate=false){stopAuto(false);$('#auto').checked=true;savePrefs({auto:true});state.nextRefresh=Date.now()+REFRESH_MS;state.timer=setInterval(()=>{if(document.hidden||closedSession())return;refreshLabel();if(state.source==='futu'&&!document.hidden&&!closedSession()&&!state.busy&&Date.now()>=state.nextRefresh){fetchLive();}},1000);if(immediate)fetchLive();refreshLabel();}
function stopAuto(save=true){if(state.timer)clearInterval(state.timer);state.timer=null;state.nextRefresh=null;$('#auto').checked=false;if(save)savePrefs({auto:false});refreshLabel();}
function refreshLabel(){
 if(closedSession()){
  $('#refresh-state').textContent=(state.record?.source==='FUTU'?'休市暂停自动刷新，可手动查询其他标的。':'休市，可手动查询富途快照。')+' 下次开盘：'+when(marketSession.expiresAt);
  return;
 }
 const ago=state.lastSuccess?`上次成功 ${when(state.lastSuccess)}。`:'';$('#refresh-state').textContent=state.timer&&document.hidden?'页面已在后台，暂停自动取数；返回后恢复。':state.timer?`${ago} 距下次刷新 ${Math.max(0,Math.ceil((state.nextRefresh-Date.now())/1000))} 秒`:`${ago} 自动刷新已暂停` ;}
function freshness(item){
 if(item.source!=='FUTU')return '';
 const rows=item.report.modes[state.basis].rows;
 const times=rows.flatMap(r=>[r.callQuote?.updatedAt,r.putQuote?.updatedAt]).filter(Boolean).map(Date.parse);
 const oldest=times.length?Math.min(...times):null;
 const stale=rows.filter(r=>r.issues.some(x=>x.includes('较旧')||x.includes('过旧'))).length;
 const phase=marketNames[item.connection?.marketUS]||item.connection?.marketUS||'市场状态未知';
 return `${phase}。${oldest!==null?`期权快照更新时间跨度：${when(new Date(oldest).toISOString())} 至 ${when(new Date(Math.max(...times)).toISOString())}。`:''}${stale?`${stale} 档含较旧快照，` :''}快照更新时间不等于独立成交/盘口时间；当前展示原始报价估值，不能视为可成交套利收益。`;
}
let manualLimits={};
function settings(){return {...manualLimits,symbol:$('#manual-symbol').value.trim().toUpperCase(),spot:num($('#manual-spot').value),expiration:$('#manual-expiry').value,valuationAt:$('#manual-asof').value.trim(),rate:Number($('#manual-rate').value)/100,timeRule:$('#manual-time-rule').value,remainingDays:$('#manual-time-rule').value==='days'?num($('#manual-days').value):null,pricingAt:$('#manual-time-rule').value==='timestamp'?$('#manual-pricing-at').value.trim():null};}
function timeFields(){const rule=$('#manual-time-rule').value;$('#manual-days-label').hidden=rule!=='days';$('#manual-pricing-label').hidden=rule!=='timestamp';}
function populateSettings(input){for(const [id,key] of [['manual-symbol','symbol'],['manual-spot','spot'],['manual-expiry','expiration'],['manual-asof','valuationAt'],['manual-days','remainingDays'],['manual-pricing-at','pricingAt']])$('#'+id).value=input[key]??'';$('#manual-rate').value=(input.rate??.05)*100;$('#manual-time-rule').value=input.timeRule||'days';manualLimits={maxAgeSeconds:input.maxAgeSeconds??60,maxSkewSeconds:input.maxSkewSeconds??5};timeFields();}
function render(){const expanded=$$('#quote-rows details[open]').map(d=>d.closest('tr').dataset.strike);const item=state.record;$('#empty').hidden=!!item;$('#study').hidden=!item;$('#export').disabled=!item;if(!item)return;
 const r=item.report,a=r.modes[state.basis];
 const implied=a.impliedSpot;
 for (const key of ['median','mean','min','max']) $('#spot-'+key).textContent=fmt(implied?.[key]);
 $('#implied-summary').textContent=implied
   ? `${basisLabel()} · USD／股 · ${implied.count}/7 档可计算`
   : '当前快照没有七档反推汇总';
 if(a.comparison)state.comparison=a.comparison;
 $('#compare').hidden=r.center!=null;
 $('#compare-method').textContent=r.center!=null?'每档用左右相邻两档作参照，最低档和最高档用同侧最近两档。七档均可计算时，按相对溢价从低到高排名。':'缺少正股现价，可单独复核三档 Call 的相对价格。';
 $('#study-symbol').textContent=r.symbol;$('#source-badge').textContent=originLabels[item.source];$('#expiry-badge').textContent=r.expiration?'到期日 '+r.expiration:'期限未提供';$('#study-time').textContent='估值时刻：'+when(r.valuationAt);
 const provenance=item.source==='FUTU'?`来自本机富途 API${item.cached?'，使用 10 秒内缓存':''}。正股快照更新：${when(item.stockUpdatedAt)}。接收时刻：${when(item.receivedAt)}。${item.stockAnchor?`选档使用${item.stockAnchor.label} ${fmt(item.stockAnchor.price)}（常规 Last ${fmt(item.stockAnchor.regularLast)}）。`:''}盘口同步性请查看下方数据说明。`:'人工输入 / 导入数据。所有时刻按输入保留，报价未独立核实。';
 $('#provenance').textContent=provenance;$('#freshness').textContent=freshness(item);
 $$('[data-basis]').forEach(b=>{b.setAttribute('aria-pressed',String(b.dataset.basis===state.basis));});
 $('#selection-note').textContent=r.center?`中心行权价 ${r.center} · 前 3 ＋ 自身 ＋ 后 3`:`候选报价 ${a.rows.length} 档 · 尚未进行七档选档`;
 $('#selection-count').textContent=r.center!=null?`本次比较 ${a.rows.length} / 7 档 Call`:item.input?`已选 ${state.selected.size} / 3 档用于 Call 比较`:'示意例不含 Call / Put';
 $('#quote-rows').innerHTML=a.rows.map(row=>`<tr data-strike="${esc(row.strike)}" class="${state.selected.has(row.strike)?'selected ':''}${row.strike===r.center?'center':''}"><td>${r.center!=null?'自动':`<input type="checkbox" data-strike="${esc(row.strike)}" aria-label="比较行权价 ${esc(row.strike)}" ${state.selected.has(row.strike)?'checked':''} ${!item.input?'disabled':''}>`}</td><td><strong>${esc(row.strike)}</strong>${row.strike===r.center?'<span class="center-tag">中心</span>':''}</td><td class="number">${fmt(row.call)}</td><td class="number">${fmt(row.put)}</td><td class="issues"><details class="quote-detail"><summary>${row.qualityPassed?'输入事件时间通过检查':esc(row.issues[0]||'暂无质量信息')}</summary><p>${row.issues.map(esc).join('；')}<br>Call 成交事件：${esc(when(row.callQuote?.lastAt))}<br>Put 成交事件：${esc(when(row.putQuote?.lastAt))}<br>Call 快照更新：${esc(when(row.callQuote?.updatedAt))}<br>Put 快照更新：${esc(when(row.putQuote?.updatedAt))}</p></details></td></tr>`).join('');
 $('#method-content').innerHTML=`<p>模型 ${esc(r.modelVersion)} · 数据来源 ${esc(originLabels[item.source])}</p><p>年利率：${r.rate==null?'未提供':fmt(r.rate*100,2)+'%'}；T：${fmt(r.T,8)} 年。${esc(r.timeNote)}</p><p>估值时刻：${esc(when(r.valuationAt))}；定价参考时刻：${esc(when(r.pricingAt))}。</p><ul>${r.notes.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><p>三档复制公式：wⱼ = (Kₖ − Kᵢ) / (Kₖ − Kⱼ)，wₖ = 1 − wⱼ；C参考 = Pᵢ + wⱼ(Cⱼ − Pⱼ) + wₖ(Cₖ − Pₖ)。溢价率 = (Call 市价 − 复制参考价) / 复制参考价。支持不等距行权价。</p><p>不同参考组会影响相对比较，排名仅针对本次参与比较的档位。程序不扣交易成本，也不验证可成交性。</p>`;
 for(const d of $$('#quote-rows details'))if(expanded.includes(d.closest('tr').dataset.strike))d.open=true;
 renderComparison();busy(state.busy);quoteAge();
}
function renderComparison(){const result=state.comparison;$('#comparison').hidden=!result;$('#compare-placeholder').hidden=!!result;if(!result){$('#comparison').innerHTML='';$('#compare-placeholder').textContent=state.record?.input?'请在候选期权报价中选择三档，查看相对溢价。':'等待 Call / Put 报价。';return;}
 const ordered=[...result.rows].sort((a,b)=>Number(a.strike)-Number(b.strike));
 const extent=Math.max(...ordered.map(r=>Math.abs(r.premiumPct??0)),0.000001);
 const pct=value=>value==null?'—':fmt(value,2)+'%';
 const ticks=ordered.map(r=>{
  const value=r.premiumPct;
  const height=value==null?0:Math.abs(value)/extent*46;
  return `<div class="plot-column" title="K ${esc(r.strike)} · ${pct(value)}">
   <div class="plot-track"><i class="${value<0?'below':'above'} ${r.rank===1?'best':''}" style="height:${height}%"></i></div>
   <span>${esc(r.strike)}</span></div>`;
 }).join('');
 const lead=result.rankable?'K '+result.lowest.map(esc).join(' / '):'暂无法排名';
 const fields=result.rows.map(r=>`<tr class="${r.rank===1?'winner':''}">
  <td><span class="rank">${r.rank??'—'}</span></td><td><strong>${esc(r.strike)}</strong></td>
  <td class="number premium">${pct(r.premiumPct)}</td><td class="number">${fmt(r.market)}</td>
  <td class="number">${fmt(r.reference)}</td><td class="refs">${r.referenceStrikes.map(esc).join(' / ')||'—'}</td></tr>`).join('');
 const derivations=result.rows.map(r=>`<details class="derivation"><summary>K ${esc(r.strike)} 的计算明细</summary>
  <p>${r.terms.map(t=>`${fmt(t.weight,4)} × ${t.right==='C'?'Call':'Put'}(${esc(t.strike)})`).join(' ＋ ')}
  <br><code>${r.terms.map(t=>`(${fmt(t.weight,4)} × ${fmt(t.price)})`).join(' + ')} = ${fmt(r.reference)}</code>
  <br>相对溢价 = (${fmt(r.market)} − ${fmt(r.reference)}) / ${fmt(r.reference)} = ${pct(r.premiumPct)}</p></details>`).join('');
 const wasOpen=$('#comparison .working')?.open;
 $('#comparison').innerHTML=`<div class="comparison-lead"><div class="verdict">
  <span class="rank-label">${result.expectedCount===7?'七档':'三档'}内相对溢价最低</span>
  <strong>${lead}</strong><span class="winner-delta">${result.rankable?'相对溢价 '+pct(result.rows[0].premiumPct):'有效档数 '+ordered.filter(r=>r.premiumPct!=null).length+' / '+result.expectedCount}</span>
  </div><figure class="premium-plot"><figcaption>各行权价相对溢价</figcaption><div class="plot-area"><small>0%</small>${ticks}</div></figure></div>
  <div class="quality-line">${esc(basisLabel())} · ${result.qualityPassed?'报价事件时间通过检查':'报价质量受限'}${result.issues.length?' · '+esc(result.issues.join('、')):''}</div>
  <div class="table-wrap" tabindex="0" aria-label="Call 排名表"><table><thead><tr><th>排名</th><th>行权价</th><th>相对溢价</th><th>Call 市价</th><th>复制参考价</th><th>参照行权价</th></tr></thead><tbody>${fields}</tbody></table></div>
  <details class="working" ${wasOpen?'open':''}><summary>查看逐档计算</summary>${derivations}</details>
  <p class="comparison-note">${esc(result.note)}</p>`;

}
async function compareSelected(){if(state.busy||!state.record?.input||state.record.report.center!=null||state.selected.size!==3)return;const epoch=++state.epoch;busy(true);message();try{await updateComparison(epoch);}catch(e){if(epoch===state.epoch)message(e.message);}finally{busy(false);}}
function editorRow(values={},original=null){const tr=document.createElement('tr');tr.originalQuote=original;tr.innerHTML=fields.map(f=>`<td><input aria-label="${esc(f)}" data-field="${f}" type="number" min="0" step="any" value="${esc(values[f]??'')}" ${f==='strike'&&original?'readonly title="已有合约行权价；更换合约请新增一行"':''} placeholder="—"></td>`).join('')+'<td><button type="button" data-remove aria-label="删除此报价行">×</button></td>';$('#editor-rows').appendChild(tr);}
function editorDrafts(){return [...$('#editor-rows').children].map(tr=>({values:Object.fromEntries([...tr.querySelectorAll('input')].map(x=>[x.dataset.field,x.value])),original:tr.originalQuote??null}));}
function populateManual(record){populateSettings(record.input);$('#editor-rows').innerHTML='';for(const row of record.input.rows){const draft=toDraft(row,record.input);editorRow(draft.values,draft.original);}saveDraft();}
function openEditor(){if(!$('#editor-rows').children.length)for(let i=0;i<7;i++)editorRow();$('#editor-error').textContent='';$('#editor').showModal();}
async function calculate(){if(state.busy)return;const epoch=++state.epoch;busy(true);$('#editor-error').textContent='';try{const rows=editorDrafts().map(d=>fromDraft(d.values,d.original)).filter(Boolean);const r=await api('/analyze',{...settings(),rows});if(epoch===state.epoch){apply(r);$('#editor').close();message();try{await updateComparison(epoch);}catch(e){message('报价已计算，但 Call 比较失败：'+e.message);}}}catch(e){$('#editor-error').textContent=e.message;}finally{busy(false);}}
async function importFile(file){if(!file)return;if(file.size>1000000){message('文件不能超过 1 MB。');return;}const epoch=++state.epoch;busy(true);message();try{const r=await api('/import',{format:file.name.toLowerCase().endsWith('.csv')?'csv':'json',content:await file.text(),settings:settings()});if(epoch===state.epoch){apply(r);await updateComparison(epoch);}}catch(e){if(epoch===state.epoch)message(e.message);}finally{busy(false);$('#file').value='';}}
function showView(view){
 $('#implied-panel').hidden=view!=='implied';
 $('#ranking-panel').hidden=view!=='ranking';
 $('#quotes-panel').hidden=view!=='quotes';
 for(const button of $$('[data-view]'))button.setAttribute('aria-pressed',String(button.dataset.view===view));
}
$$('[data-view]').forEach(button=>button.addEventListener('click',()=>showView(button.dataset.view)));
const compact=window.matchMedia('(max-width: 800px)');
const controls=$('#controls-panel');
controls.open=!compact.matches;
compact.addEventListener('change',()=>{controls.open=!compact.matches;});
$('#empty-settings').addEventListener('click',()=>{
 controls.open=true;
 controls.scrollIntoView({block:'start'});
 controls.querySelector('button[aria-selected="true"]').focus();
});
$$('[data-source]').forEach(b=>b.addEventListener('click',()=>{source(b.dataset.source);if(b.dataset.source==='futu'){if(readPrefs().auto!==false)startAuto();syncSession().then(()=>fetchLive()).catch(e=>message(e.message));}}));
$$('[data-ticker]').forEach(b=>b.addEventListener('click',()=>{$('#symbol').value=b.dataset.ticker;if(!state.busy)fetchLive(true);}));
$$('[data-basis]').forEach(b=>b.addEventListener('click',()=>{state.epoch++;state.basis=b.dataset.basis;savePrefs({basis:state.basis});state.comparison=null;render();compareSelected();}));
$('#fetch-live').addEventListener('click',()=>fetchLive(true));$('#symbol').addEventListener('keydown',e=>{if(e.key==='Enter')fetchLive(true);});$('#check-connection').addEventListener('click',checkConnection);$('#auto').addEventListener('change',e=>{if(e.target.checked)startAuto(true);else stopAuto();});
$('#quote-rows').addEventListener('change',e=>{const box=e.target;if(!box.matches('[data-strike]'))return;state.epoch++;message();if(box.checked&&state.selected.size>=3){box.checked=false;message('一次比较三个行权价，请先取消一档。');return;}box.checked?state.selected.add(box.dataset.strike):state.selected.delete(box.dataset.strike);state.comparison=null;render();compareSelected();});
$('#compare').addEventListener('click',compareSelected);$('#open-editor').addEventListener('click',openEditor);$('#add-row').addEventListener('click',()=>editorRow());$('#calculate').addEventListener('click',calculate);$('#editor-rows').addEventListener('click',e=>{if(e.target.closest('[data-remove]')){e.target.closest('tr').remove();saveDraft();}});$('#file').addEventListener('change',e=>importFile(e.target.files[0]));
$('#export').addEventListener('click',()=>{if(!state.record)return;const data={...state.record,comparison:state.comparison};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`strike-lab-${state.record.report.symbol}-${state.record.id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$('#manual-asof').value=new Date().toISOString();$('#manual-expiry').value=new Date(Date.now()+7*86400000).toISOString().slice(0,10);
$('#clear-rows').addEventListener('click',()=>{$('#editor-rows').innerHTML='';for(let i=0;i<7;i++)editorRow();saveDraft();});
function saveDraft(){try{localStorage.setItem('strike-lab-draft',JSON.stringify({version:2,settings:settings(),rows:editorDrafts()}));}catch{}}
$('#editor-rows').addEventListener('input',saveDraft);$('#manual-controls').addEventListener('input',saveDraft);
const prefs=readPrefs();$('#symbol').value=prefs.symbol||'SPY';
try{const draft=JSON.parse(localStorage.getItem('strike-lab-draft')||'null');if(draft?.settings){populateSettings(draft.settings);for(const row of (Array.isArray(draft.rows)?draft.rows:[]).slice(0,500))editorRow(draft.version===2?row.values:row,draft.version===2?row.original:null);}}catch{}
$('#manual-time-rule').addEventListener('change',()=>{timeFields();saveDraft();});timeFields();
window.addEventListener('beforeunload',()=>stopAuto(false));
(async()=>{
 try{await syncSession();}catch(e){message(e.message);}
 await checkConnection();
 if(state.source==='futu'){
  if(prefs.auto!==false)startAuto();
  const requested=new URLSearchParams(location.search).get('symbol');
  if(requested && /^(?:US\.)?[A-Z][A-Z0-9.-]{0,12}$/.test(requested)){
   if(state.record?.report.symbol!==requested){state.record=null;state.comparison=null;render();}
   $('#symbol').value=requested;
   await fetchLive(true);
  }else if(!closedSession()&&state.connection?.quoteLoggedIn)await fetchLive();
 }
})();

function quoteAge(){const el=$('#quote-age');if(!el)return;const item=state.record;if(item?.source!=='FUTU'){el.textContent='';return;}if(closedSession()){
 el.textContent='休市保留 · 原报价接收于 '+when(item.receivedAt);el.classList.add('old');return;
 }const age=Math.max(0,Math.floor((Date.now()-Date.parse(item.receivedAt))/1000));el.textContent=`当前快照已接收 ${age<60?age+' 秒':Math.floor(age/60)+' 分 '+age%60+' 秒'}${age*1000>=2*REFRESH_MS?' · 已超过两个刷新周期，请刷新后再比较':''}`;el.classList.toggle('old',age*1000>=2*REFRESH_MS);}
setInterval(()=>{sessionTick();if(!document.hidden&&!closedSession())quoteAge();},1000);
window.addEventListener('pageshow',sessionTick);
document.addEventListener('visibilitychange',()=>{sessionTick();refreshLabel();if(!document.hidden&&!closedSession()&&state.timer&&state.source==='futu'&&!state.busy&&Date.now()>=state.nextRefresh)fetchLive();});
