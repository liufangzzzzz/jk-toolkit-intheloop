import type { Catalogue, Content, Locale } from './atlas';
export const mapGroups = [
  { id: 'form', zh: '本体', en: 'Robot bodies' },
  { id: 'technology', zh: '模型', en: 'Models' },
  { id: 'value_chain', zh: '数据与部件', en: 'Data & components' },
  { id: 'application', zh: '应用', en: 'Applications' },
];
export function timeline(data: Catalogue, filter: {group?:string;tag?:string;company?:string}) {
  const tags = data.tags.filter(t => filter.tag ? t.slug === filter.tag : filter.group ? t.dimension === filter.group : true);
  const ids = new Set(tags.map(t=>t.id));
  const rank=(t:Catalogue['tags'][number])=>t.map_level==='primary'?3:t.map_level==='medium'?2:1;
  // Follow only descending relationships; same-level links never widen results.
  let changed=true;
  while(changed){changed=false;for(const root of data.tags.filter(t=>ids.has(t.id))){
    for(const child of data.tags){if(!ids.has(child.id)&&rank(child)<rank(root)&&
      (root.related_tag_ids?.includes(child.id)||child.related_tag_ids?.includes(root.id)||child.parent_ids?.includes(root.id))){ids.add(child.id);changed=true}}
  }}
  const company = data.companies.find(c=>c.slug===filter.company);
  return data.contents.filter(c=>
    (!filter.company || (!!company&&c.company_ids.includes(company.id))) &&
    (!(filter.group||filter.tag) || c.tag_ids.some(id=>ids.has(id)))
  ).sort((a,b)=>b.date.localeCompare(a.date));
}

export type EditorialView = 'article' | 'podcast' | 'worldview' | 'thinking' | 'overseas';
export function editorialView(data: Catalogue, view?: string) {
  const entries = timeline(data, {});
  const fixed:Record<string,string>={article:'editorial:article',podcast:'editorial:podcast',worldview:'editorial:worldview',thinking:'editorial:thinking',overseas:'editorial:overseas'};
  if (view && fixed[view]) return entries.filter(content => content.tag_ids.includes(fixed[view]));
  return entries;
}
export function contentTarget(content: Content, locale: Locale) {
  const version = content.versions[locale];
  const external = version?.destination === 'external' || (!version?.destination&&locale==='zh'&&!!content.source_url);
  const url = version?.external_url || content.source_url;
  return {href:external&&url?url:`/${locale}?content=${content.id}`, external:!!(external&&url)};
}
export function sourceName(url:string, locale:Locale) {
  try {
    const host = new URL(url).hostname.replace(/^www\./,'');
    if(host==='mp.weixin.qq.com')return locale==='zh'?'微信公众号':'WeChat';
    if(host==='xiaoyuzhoufm.com'||host.endsWith('.xiaoyuzhoufm.com'))return locale==='zh'?'小宇宙':'Xiaoyuzhou';
    if(host==='linkedin.com'||host.endsWith('.linkedin.com'))return 'LinkedIn';
    if(host==='geekpark.net'||host.endsWith('.geekpark.net'))return locale==='zh'?'极客公园':'GeekPark';
    return host;
  }catch{return locale==='zh'?'原文':'Source'}
}

export function brandName(content:Content,locale:Locale){
 const account=content.source_account;
 if(account){if(account.includes('极客公园'))return locale==='zh'?'极客公园':'GeekPark';if(account.includes('开始连接')||account.toLowerCase().includes('linkstart'))return locale==='zh'?'开始连接 LinkStart':'LinkStart';return account}
 const brand=content.brand||(content.kind==='podcast'?'linkstart':content.source_url.includes('geekpark.net')?'geekpark':'intheloop');
 return brand==='linkstart'?(locale==='zh'?'开始连接 LinkStart':'LinkStart'):brand==='geekpark'?(locale==='zh'?'极客公园':'GeekPark'):'In The Loop';
}

export function searchCatalogue(data:Catalogue,query:string,locale:Locale){
 const key=query.trim().toLocaleLowerCase();
 if(!key)return {tags:[],entries:timeline(data,{})};
 const names=(t:Catalogue['tags'][number])=>[t.name_zh,t.name_en,...(t.aliases||[])].filter(Boolean).map(n=>n.toLocaleLowerCase());
 const exact=data.tags.filter(t=>names(t).includes(key));
 const tags=exact.length?exact:data.tags.filter(t=>names(t).some(n=>n.includes(key)));
 const ids=new Set(tags.flatMap(t=>timeline(data,{tag:t.slug}).map(c=>c.id)));
 const entries=timeline(data,{}).filter(c=>ids.has(c.id)||(!exact.length&&[c.versions[locale]?.title,c.versions[locale]?.summary,c.versions[locale]?.body].some(v=>v?.toLocaleLowerCase().includes(key))));
 return {tags,entries};
}
