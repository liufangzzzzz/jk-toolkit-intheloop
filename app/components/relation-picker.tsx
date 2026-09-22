'use client';
import {useState} from 'react';
export type RelationOption={id:string;name:string;detail?:string;keywords?:string};
export default function RelationPicker({label,options,value,onChange,suggestions=[],hint,disabled=false}:{label:string;options:RelationOption[];value:string[];onChange:(ids:string[])=>void;suggestions?:string[];hint?:string;disabled?:boolean}){
 const [query,setQuery]=useState(''),[open,setOpen]=useState(false);
 const toggle=(id:string)=>onChange(value.includes(id)?value.filter(x=>x!==id):[...value,id]);
 const suggested=options.filter(o=>suggestions.includes(o.id)&&!value.includes(o.id));
 const filtered=options.filter(o=>!value.includes(o.id)&&`${o.name} ${o.detail||''} ${o.keywords||''}`.toLowerCase().includes(query.toLowerCase()));
 return <section className="relation-picker" aria-label={label}>
  <div className="relation-heading"><h3>{label}</h3><span>{value.length} 已选</span></div>
  {hint&&<p className="relation-hint">{hint}</p>}
  {!!value.length&&<div className="relation-selected">{value.map(id=>{const item=options.find(o=>o.id===id);return <button type="button" disabled={disabled} key={id} onClick={()=>toggle(id)} aria-label={`移除${item?.name||id}`}>{item?.name||'未找到资料'}{item?.detail&&<small className="relation-level">{item.detail}</small>}<span>×</span></button>})}</div>}
  <input disabled={disabled} aria-label={`搜索${label}`} placeholder="搜索名称、别名…" value={query} onFocus={()=>setOpen(true)} onChange={e=>{setQuery(e.target.value);setOpen(true)}}/>
  {open&&<div className="relation-results"><div className="relation-result-heading"><span>{query?'搜索结果':'可选资料'}</span><button type="button" onClick={()=>setOpen(false)}>收起</button></div>{filtered.slice(0,12).map(o=><button type="button" key={o.id} disabled={disabled} onClick={()=>{toggle(o.id);setQuery('')}}><span>{o.name}<small>{o.detail}</small></span><span>＋</span></button>)}{!filtered.length&&<p>没有匹配的资料，可在资料库中新增。</p>}{filtered.length>12&&<p>输入关键词缩小范围。</p>}</div>}
  {!!suggested.length&&<div className="relation-suggestions"><span>相关，可选加入</span>{suggested.slice(0,8).map(o=><button type="button" disabled={disabled} key={o.id} onClick={()=>toggle(o.id)}>＋ {o.name}{o.detail&&<small className="relation-level">{o.detail}</small>}</button>)}</div>}
 </section>
}
