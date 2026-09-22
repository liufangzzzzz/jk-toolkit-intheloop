import assert from 'node:assert/strict';
import test from 'node:test';
import {timeline,contentTarget,editorialView} from '../lib/atlas-public.ts';
test('article topics are explicit; company tags do not silently widen a timeline',()=>{
 const data={tags:[{id:'a',slug:'wheel',dimension:'form'},{id:'b',slug:'humanoid',dimension:'form'}],companies:[{id:'co',tag_ids:['a']}],contents:[{id:'1',date:'2026-01-01',tag_ids:['a'],company_ids:['co']},{id:'2',date:'2026-02-01',tag_ids:['b'],company_ids:[]},{id:'3',date:'2026-03-01',tag_ids:[],company_ids:['co']}]};
 assert.deepEqual(timeline(data,{group:'form'}).map(x=>x.id),['2','1']);
 assert.deepEqual(timeline(data,{tag:'wheel'}).map(x=>x.id),['1']);
});
test('Chinese original links and English hosted text have separate destinations',()=>{
 const c={id:'a',source_url:'https://mp.weixin.qq.com/s/test',versions:{zh:{destination:'external'},en:{destination:'hosted'}}};
 assert.equal(contentTarget(c,'zh').href,c.source_url);
 assert.deepEqual(contentTarget(c,'en'),{href:'/en?content=a',external:false});
});

test('home editorial filters use hidden taxonomy tags',()=>{
 const data={tags:[],companies:[],contents:[
  {id:'a',date:'2026-01-03',tag_ids:['editorial:article'],company_ids:[],kind:'article',section:'reporting'},
  {id:'p',date:'2026-01-02',tag_ids:['editorial:podcast'],company_ids:[],kind:'podcast',section:'reporting'},
  {id:'w',date:'2026-01-01',tag_ids:['editorial:worldview','editorial:article'],company_ids:[],kind:'article',section:'reporting'},
 ]};
 assert.deepEqual(editorialView(data,'article').map(c=>c.id),['a','w']);
 assert.deepEqual(editorialView(data,'podcast').map(c=>c.id),['p']);
 assert.deepEqual(editorialView(data,'worldview').map(c=>c.id),['w']);
});

test('parent tags include descendants but related tags do not imply content membership',()=>{
 const data={tags:[{id:'body',slug:'body',dimension:'form',map_level:'primary',related_tag_ids:['brain']},{id:'wheel',slug:'wheel',dimension:'form',parent_ids:['body']},{id:'brain',slug:'brain',dimension:'technology',map_level:'primary'}],companies:[],contents:[{id:'a',date:'2026-01-01',tag_ids:['wheel'],company_ids:[]},{id:'b',date:'2026-02-01',tag_ids:['brain'],company_ids:[]}]};
 assert.deepEqual(timeline(data,{tag:'body'}).map(x=>x.id),['a']);
});

test('large tags aggregate related small tags; exact tag search returns that same set',async()=>{
 const {searchCatalogue}=await import('../lib/atlas-public.ts');
 const data={tags:[{id:'body',slug:'body',name_zh:'本体',name_en:'Bodies',map_visible:true,map_level:'primary',related_tag_ids:['wheel','brain']},{id:'wheel',slug:'wheel',name_zh:'轮式',name_en:'Wheeled',map_level:'secondary',related_tag_ids:['body','other']},{id:'brain',slug:'brain',name_zh:'大脑',name_en:'Brain',map_visible:true,map_level:'primary'},{id:'other',slug:'other',name_zh:'其他',name_en:'Other'}],companies:[],contents:[{id:'a',date:'2026-01-01',tag_ids:['wheel'],versions:{zh:{title:'轮式文章'}}},{id:'b',date:'2026-01-02',tag_ids:['brain'],versions:{zh:{title:'本体仅在标题中'}}},{id:'c',date:'2026-01-03',tag_ids:['other'],versions:{zh:{title:'其他'}}}]};
 assert.deepEqual(timeline(data,{tag:'body'}).map(c=>c.id),['a']);
 assert.deepEqual(timeline(data,{tag:'wheel'}).map(c=>c.id),['a']);
 assert.deepEqual(searchCatalogue(data,'本体','zh').entries.map(c=>c.id),['a']);
 assert.deepEqual(searchCatalogue(data,'Bodies','en').entries.map(c=>c.id),['a']);
 assert.deepEqual(searchCatalogue(data,'不存在','zh').entries,[]);
});

 test('three levels descend transitively without following peers or going upward',async()=>{
 const {searchCatalogue}=await import('../lib/atlas-public.ts');
 const tags=[{id:'l',slug:'large',name_zh:'大',map_level:'primary',related_tag_ids:['m']},{id:'m',slug:'medium',name_zh:'中',map_level:'medium',related_tag_ids:['s','peer']},{id:'s',slug:'small',name_zh:'小',map_level:'secondary',map_visible:false},{id:'peer',slug:'peer',name_zh:'同级',map_level:'medium'}];
 const data={tags,companies:[],contents:tags.map(t=>({id:t.id,date:'2026-01-01',tag_ids:[t.id],versions:{zh:{title:t.name_zh}}}))};
 assert.deepEqual(timeline(data,{tag:'large'}).map(c=>c.id),['l','m','s']);
 assert.deepEqual(timeline(data,{tag:'medium'}).map(c=>c.id),['m','s']);
 assert.deepEqual(timeline(data,{tag:'small'}).map(c=>c.id),['s']);
 assert.deepEqual(searchCatalogue(data,'大','zh').entries.map(c=>c.id),['l','m','s']);
 });
