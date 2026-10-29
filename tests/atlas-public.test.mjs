import assert from 'node:assert/strict';
import test from 'node:test';
import {timeline,contentTarget,editorialView} from '../lib/atlas-public.ts';
test('article topics are explicit; company tags do not silently widen a timeline',()=>{
 const data={tags:[{id:'a',slug:'wheel',dimension:'form'},{id:'b',slug:'humanoid',dimension:'form'}],companies:[{id:'co',tag_ids:['a']}],contents:[{id:'1',date:'2026-01-01',tag_ids:['a'],company_ids:['co']},{id:'2',date:'2026-02-01',tag_ids:['b'],company_ids:[]},{id:'3',date:'2026-03-01',tag_ids:[],company_ids:['co']}]};
 assert.deepEqual(timeline(data,{group:'form'}).map(x=>x.id),['2','1']);
 assert.deepEqual(timeline(data,{tag:'wheel'}).map(x=>x.id),['1']);
});
test('Latest accepts year, month, or day precision and keeps reverse chronological order',()=>{
 const data={tags:[],companies:[],contents:[
  {id:'year',date:'2024',tag_ids:[],company_ids:[]},
  {id:'month',date:'2025-06',tag_ids:[],company_ids:[]},
  {id:'day',date:'2025-06-18',tag_ids:[],company_ids:[]},
 ]};
 assert.deepEqual(timeline(data,{}).map(c=>c.id),['day','month','year']);
});
test('Chinese original links and English hosted text have separate destinations',()=>{
 const c={id:'a',source_url:'https://mp.weixin.qq.com/s/test',versions:{zh:{destination:'external'},en:{destination:'hosted'}}};
 assert.equal(contentTarget(c,'zh').href,c.source_url);
 assert.deepEqual(contentTarget(c,'en'),{href:'/en?content=a',external:false});
});

test('home views keep Featured ordering and Conversations taxonomy separate',()=>{
 const data={tags:[],companies:[],homepage_featured_ids:['w','a'],contents:[
  {id:'a',date:'2026-01-03',tag_ids:['editorial:article'],company_ids:[],kind:'article',section:'reporting'},
  {id:'p',date:'2026-01-02',tag_ids:['editorial:podcast'],company_ids:[],kind:'podcast',section:'reporting'},
  {id:'w',date:'2026-01-01',tag_ids:['editorial:conversations','editorial:article'],company_ids:[],kind:'article',section:'reporting'},
 ]};
 assert.deepEqual(editorialView(data,'featured').map(c=>c.id),['w','a']);
 assert.deepEqual(editorialView(data,'podcast').map(c=>c.id),['p']);
 assert.deepEqual(editorialView(data,'conversations').map(c=>c.id),['w']);
});

test('topic pages include only directly tagged content, not descendants or related topics',()=>{
 const data={tags:[{id:'body',slug:'body',dimension:'form',map_level:'primary',related_tag_ids:['brain']},{id:'wheel',slug:'wheel',dimension:'form',parent_ids:['body']},{id:'brain',slug:'brain',dimension:'technology',map_level:'primary'}],companies:[],contents:[{id:'a',date:'2026-01-01',tag_ids:['wheel'],company_ids:[]},{id:'b',date:'2026-02-01',tag_ids:['brain'],company_ids:[]}]};
 assert.deepEqual(timeline(data,{tag:'body'}).map(x=>x.id),[]);
 assert.deepEqual(timeline(data,{tag:'wheel'}).map(x=>x.id),['a']);
});

test('map size and related tags do not change direct topic membership',async()=>{
 const {searchCatalogue}=await import('../lib/atlas-public.ts');
 const data={tags:[{id:'body',slug:'body',name_zh:'本体',name_en:'Bodies',map_visible:true,map_level:'primary',related_tag_ids:['wheel','brain']},{id:'wheel',slug:'wheel',name_zh:'轮式',name_en:'Wheeled',map_level:'secondary',related_tag_ids:['body','other']},{id:'brain',slug:'brain',name_zh:'大脑',name_en:'Brain',map_visible:true,map_level:'primary'},{id:'other',slug:'other',name_zh:'其他',name_en:'Other'}],companies:[],contents:[{id:'a',date:'2026-01-01',tag_ids:['wheel'],versions:{zh:{title:'轮式文章'}}},{id:'b',date:'2026-01-02',tag_ids:['brain'],versions:{zh:{title:'本体仅在标题中'}}},{id:'c',date:'2026-01-03',tag_ids:['other'],versions:{zh:{title:'其他'}}}]};
 assert.deepEqual(timeline(data,{tag:'body'}).map(c=>c.id),[]);
 assert.deepEqual(timeline(data,{tag:'wheel'}).map(c=>c.id),['a']);
 assert.deepEqual(searchCatalogue(data,'本体','zh').entries.map(c=>c.id),[]);
 assert.deepEqual(searchCatalogue(data,'Bodies','en').entries.map(c=>c.id),[]);
 assert.deepEqual(searchCatalogue(data,'不存在','zh').entries,[]);
});

 test('arbitrary-depth hierarchy is navigation only and does not widen reports',async()=>{
 const {searchCatalogue}=await import('../lib/atlas-public.ts');
 const tags=[{id:'l',slug:'large',name_zh:'大',map_level:'primary',related_tag_ids:['m']},{id:'m',slug:'medium',name_zh:'中',map_level:'medium',related_tag_ids:['s','peer']},{id:'s',slug:'small',name_zh:'小',map_level:'secondary',map_visible:false},{id:'peer',slug:'peer',name_zh:'同级',map_level:'medium'}];
 const data={tags,companies:[],contents:tags.map(t=>({id:t.id,date:'2026-01-01',tag_ids:[t.id],versions:{zh:{title:t.name_zh}}}))};
 assert.deepEqual(timeline(data,{tag:'large'}).map(c=>c.id),['l']);
 assert.deepEqual(timeline(data,{tag:'medium'}).map(c=>c.id),['m']);
 assert.deepEqual(timeline(data,{tag:'small'}).map(c=>c.id),['s']);
 assert.deepEqual(searchCatalogue(data,'大','zh').entries.map(c=>c.id),['l']);
 });
