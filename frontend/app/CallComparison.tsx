'use client';
import { useEffect,useRef,useState } from 'react';
import { api,fmt,labels,type Obj } from './lib';
import { Button } from '@/components/ui/button';
export function CallComparison({monitorId,snapshotId,basis,rows,time}:{monitorId:string,snapshotId?:number,basis:string,rows:Obj[],time:(v:any)=>string}){
 const keys=rows.map(r=>r.strike) as string[], signature=keys.join('|');
 const [chosen,setChosen]=useState<string[]>([]),[result,setResult]=useState<Obj|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const request=useRef(0);
 useEffect(()=>{request.current++;setBusy(false);setResult(null);setError('');setChosen(keys.slice(Math.max(0,Math.floor(keys.length/2)-1),Math.max(0,Math.floor(keys.length/2)-1)+3));},[signature]);
 useEffect(()=>()=>{request.current++;},[]);
 async function compare(){const id=++request.current;setBusy(true);setError('');try{const r=await api(`/monitors/${monitorId}/call-comparison`,{snapshotId,basis,strikes:chosen});if(id===request.current)setResult(r);}catch(e){if(id===request.current)setError(e instanceof Error?e.message:String(e));}finally{if(id===request.current)setBusy(false);}}
 return <section className="pairs call-comparison"><div className="section-heading"><h3>Call 相对价格比较 <span>三档复制成本</span></h3></div><p className="fine">从当前选档中任选三个行权价，用另外两档 Call／Put 与本档 Put 推导参考 Call 价格；支持不等距行权价。当前口径：{labels[basis]}。</p>
 <div className="comparison-controls">{[0,1,2].map(i=><label key={i}>行权价 {i+1}<select aria-label={`比较行权价 ${i+1}`} value={chosen[i]||''} onChange={e=>{request.current++;setBusy(false);setResult(null);setChosen(chosen.map((v,j)=>j===i?e.target.value:v));}}><option value="" disabled>请选择</option>{keys.map(k=><option key={k} value={k}>{k}</option>)}</select></label>)}<Button disabled={busy||!snapshotId||chosen.length!==3||new Set(chosen).size!==3} onClick={compare}>{busy?'计算中…':'比较这三档'}</Button></div>
 {keys.length<3&&<p className="amber-text">至少需要三个选中行权价。</p>}{error&&<p role="alert" className="amber-text">{error}</p>}
 {result&&<><p className="fine">计算快照：{time(result.valuationAt)} · {result.feedType} · 到期日 {result.expiration}{result.snapshotId!==snapshotId?' · 已有更新报价，请重新比较':''} · {result.qualityEligible?'报价质量合格':'报价质量未通过，仅作原始价格对比'}</p><div className="table-scroll"><table><thead><tr>{['行权价','Call 市价','复制参考价','相对溢价','三档内排名'].map(x=><th key={x}>{x}</th>)}</tr></thead><tbody>{result.rows.map((r:Obj)=><tr key={r.strike}><td>{r.strike}</td><td>{fmt(r.marketCall)}</td><td>{fmt(r.referenceCall)}</td><td className={r.premiumPct<0?'accent':''}>{r.premiumPct==null?'—':fmt(r.premiumPct,2)+'%'}</td><td>{r.rank==null?'无法排名':r.rank===1?'1 · 相对最低':r.rank}</td></tr>)}</tbody></table></div><p className="fine">{result.warning}</p>{result.reasons.length>0&&<p className="amber-text">{result.reasons.join(' · ')}</p>}</>}
 </section>;
}
