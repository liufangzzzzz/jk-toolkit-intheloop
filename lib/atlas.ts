export type Locale = "zh" | "en";
export type Tag = {
  tag_type?: "content_type" | "entity" | "technical_topic" | "topic" | "company" | "product";
  entity_kind?: "company" | "product" | "person" | null;
  visibility?: "public" | "internal";
  affiliations?: {company_id:string;relationship:"employment"|"founder"|"advisor"|"board"|"other";is_primary?:boolean;title_zh?:string;title_en?:string;start_date?:string;end_date?:string;status?:"current"|"former"}[];
  map_level?: "primary" | "medium" | "secondary";
  aliases?: string[];
  website?: string;
  announced_date?: string;
  released_date?: string;
  ended_date?: string;
  map_visible?: boolean;
  parent_ids?: string[];
  related_tag_ids?: string[];
  featured_content_ids?: string[];
  id: string;
  revision: number;
  slug: string;
  name_zh: string;
  name_en: string;
  dimension: string;
  description_zh: string;
  description_en: string;
  visible_locales: Locale[];
};
export type TagLink = {
  tag_id: string;
  evidence_url: string;
  note: string;
  verified_at?: string;
};
export type Company = {
  map_visible?: boolean;
  id: string;
  revision: number;
  slug: string;
  name_zh: string;
  name_en: string;
  aliases: string[];
  summary_zh: string;
  summary_en: string;
  website: string;
  region: string;
  visible_locales: Locale[];
  tag_links: TagLink[];
  tag_ids?: string[];
};
export type Product = {
  id: string;
  revision: number;
  company_id: string;
  name_zh: string;
  name_en: string;
  summary_zh: string;
  summary_en: string;
  tag_ids: string[];
  visible_locales: Locale[];
};
export type Version = {
  title: string;
  summary: string;
  reading_hint?: string;
  body: string;
  destination?: "hosted" | "external";
  external_url?: string;
  platform?: string;
  links?: { label: string; url: string }[];
};
export type Content = {
  visibility?: "public" | "internal";
  chinese_only?: boolean;
  source_account?: string;
  brand?: "geekpark" | "intheloop" | "linkstart";
  resources?: {label:string;label_en?:string;url:string;kind:"article"|"website"|"podcast"|"other"}[];
  id: string;
  revision: number;
  kind: "article" | "podcast" | "link";
  section: "reporting" | "overseas";
  source_url: string;
  date: string;
  audio_language: Locale;
  guests: string;
  duration: string;
  company_ids: string[];
  tag_ids: string[];
  ai_recommended_tag_ids?: string[];
  ai_suggested_tags?: string[];
  versions: Partial<Record<Locale, Version>>;
  publications?: {
    locale: Locale;
    revision: number;
    published_at: string;
  }[];
};
export type Catalogue = {
  companies: Company[];
  tags: Tag[];
  products: Product[];
  contents: Content[];
  homepage_featured_ids?: string[];
};
export const dimensions: Record<string, string> = {
  technology: "技术路线",
  form: "本体形态",
  value_chain: "产业环节",
  application: "应用场景",
};
export const enDimensions: Record<string, string> = {
  technology: "Technology",
  form: "Robot form",
  value_chain: "Value chain",
  application: "Applications",
};
export const blankVersion: Version = { title: "", summary: "", reading_hint: "", body: "" };
