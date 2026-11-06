from typing import Literal
from datetime import date as calendar_date
from urllib.parse import urlparse
from pydantic import BaseModel, Field, field_validator, model_validator

Locale = Literal['zh', 'en']
Visibility = Literal['public', 'internal']

class Base(BaseModel):
    revision: int = 0

class Link(BaseModel):
    tag_id: str
    evidence_url: str = ''
    note: str = ''
    verified_at: str = ''

    @field_validator('evidence_url')
    @classmethod
    def url(cls, value): return valid_url(value)


def valid_url(value):
    if value and (urlparse(value).scheme not in ('http','https') or not urlparse(value).netloc):
        raise ValueError('链接须以 https:// 或 http:// 开头')
    return value

class Company(Base):
    map_visible: bool = False
    slug: str = Field(pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$', max_length=100)
    name_zh: str = Field(min_length=1, max_length=180)
    name_en: str = ''
    aliases: list[str] = Field(default_factory=list)
    summary_zh: str = ''
    summary_en: str = ''
    website: str = ''
    region: str = ''
    visible_locales: list[Locale] = Field(default_factory=list)
    tag_links: list[Link] = Field(default_factory=list)

    @field_validator('website')
    @classmethod
    def url(cls, value): return valid_url(value)

class Affiliation(BaseModel):
    company_id: str
    relationship: Literal['employment','founder','advisor','board','other'] = 'employment'
    is_primary: bool = True
    title_zh: str = ''
    title_en: str = ''
    start_date: str = ''
    end_date: str = ''

class Tag(Base):
    tag_type: Literal["content_type","entity","technical_topic","topic","company","product"] = "technical_topic"
    entity_kind: Literal["company","product","person"] | None = None
    visibility: Visibility = 'public'
    affiliations: list[Affiliation] = Field(default_factory=list)
    map_level: Literal["primary","medium","secondary"] = "secondary"
    aliases: list[str] = Field(default_factory=list)
    website: str = ""
    announced_date: str = Field(default='', pattern=r'^(?:\d{4}(?:-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?)?)?$')
    released_date: str = Field(default='', pattern=r'^(?:\d{4}(?:-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?)?)?$')
    ended_date: str = Field(default='', pattern=r'^(?:\d{4}(?:-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?)?)?$')

    @field_validator("website")
    @classmethod
    def check_website(cls, value): return valid_url(value)

    @field_validator('announced_date','released_date','ended_date')
    @classmethod
    def valid_product_date(cls, value):
        if len(value) == 10:
            try: calendar_date.fromisoformat(value)
            except ValueError as exc: raise ValueError('产品时间不是有效日期') from exc
        return value

    map_visible: bool = True
    parent_ids: list[str] = Field(default_factory=list)
    related_tag_ids: list[str] = Field(default_factory=list)
    featured_content_ids: list[str] = Field(default_factory=list)
    slug: str = Field(pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$', max_length=100)
    name_zh: str = Field(min_length=1, max_length=100)
    name_en: str = ''
    dimension: Literal['technology','form','value_chain','application'] = 'technology'
    description_zh: str = ''
    description_en: str = ''
    visible_locales: list[Locale] = Field(default_factory=lambda: ['zh','en'])

class Product(Base):
    company_id: str
    name_zh: str = Field(min_length=1, max_length=180)
    name_en: str = ''
    summary_zh: str = ''
    summary_en: str = ''
    tag_ids: list[str] = Field(default_factory=list)
    visible_locales: list[Locale] = Field(default_factory=list)

class Resource(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1)

    @field_validator("url")
    @classmethod
    def check_url(cls, value): return valid_url(value)

class Companion(Resource):
    label_en: str = ""
    kind: Literal["article","website","podcast","other"] = "article"

class Terminology(BaseModel):
    zh: str = Field(min_length=1, max_length=160)
    en: str = Field(default='', max_length=240)
    kind: Literal['company','person','product','technical','other'] = 'other'
    confirmed: bool = False

class MediaAsset(BaseModel):
    type: Literal['image','gif','video'] = 'image'
    url: str = Field(min_length=1, max_length=500)
    alt: str = Field(default='', max_length=300)
    caption: str = Field(default='', max_length=500)
    placement: Literal['unplaced','before_body','inline','after_body'] = 'before_body'
    inline_offsets: dict[Locale, int] = Field(default_factory=dict)

    @field_validator('url')
    @classmethod
    def media_url(cls, value):
        if value.startswith('ingest-asset://'):
            return value
        return valid_url(value)

class ImportURL(BaseModel):
    url: str = Field(min_length=1, max_length=4000)

class Version(BaseModel):
    title: str = Field(default='', max_length=250)
    summary: str = ''
    reading_hint: str = ''
    body: str = ''
    destination: Literal['hosted','external'] = 'hosted'
    external_url: str = ''
    platform: str = ''
    links: list[Resource] = Field(default_factory=list)

    @field_validator('external_url')
    @classmethod
    def url(cls, value): return valid_url(value)

class Content(Base):
    source_locale: Locale = 'zh'
    source_account: str = Field(default='', max_length=180)
    @model_validator(mode='before')
    @classmethod
    def defaults(cls, value):
        if isinstance(value,dict):
            value = dict(value)
            if not value.get('brand'):
                value['brand'] = 'intheloop'
            raw_date = str(value.get('date') or '').strip()
            if raw_date:
                raw_date = raw_date.replace('年','-').replace('月','-').replace('日','').replace('/','-').replace('.','-').rstrip('-')
                parts = raw_date.split('-')
                if len(parts) in (2,3) and all(part.isdigit() for part in parts):
                    raw_date = '-'.join([parts[0], *[part.zfill(2) for part in parts[1:]]])
                value['date'] = raw_date
            # The companion-link editor may contain a newly-added, untouched row.
            # The whole section is optional, so do not turn that UI state into a 422.
            resources = value.get('resources')
            if isinstance(resources, list):
                value['resources'] = [
                    resource for resource in resources
                    if not isinstance(resource, dict)
                    or any(str(resource.get(field) or '').strip() for field in ('label', 'label_en', 'url'))
                ]
        return value

    chinese_only: bool = False
    visibility: Visibility = 'public'
    brand: Literal["geekpark","intheloop","linkstart"] = "intheloop"
    resources: list[Companion] = Field(default_factory=list)
    kind: Literal['article','podcast','link'] = 'article'
    section: Literal['reporting','overseas'] = 'reporting'
    source_url: str = ''
    date: str = Field(pattern=r'^\d{4}(?:-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?)?$')
    audio_language: Locale = 'zh'
    guests: str = ''
    duration: str = ''
    company_ids: list[str] = Field(default_factory=list)
    tag_ids: list[str] = Field(default_factory=list)
    ai_recommended_tag_ids: list[str] = Field(default_factory=list)
    ai_suggested_tags: list[str] = Field(default_factory=list)
    terminology: list[Terminology] = Field(default_factory=list)
    media: list[MediaAsset] = Field(default_factory=list, max_length=100)
    featured_locales: list[Locale] = Field(default_factory=list)
    versions: dict[Locale, Version]

    @field_validator('source_url')
    @classmethod
    def url(cls, value): return valid_url(value)

    @field_validator('date')
    @classmethod
    def valid_partial_date(cls, value):
        if len(value) == 10:
            try: calendar_date.fromisoformat(value)
            except ValueError as exc: raise ValueError('发布日期不是有效日期') from exc
        return value

class Publication(BaseModel):
    locale: Locale
    revision: int

class Generate(BaseModel):
    model: str = Field(min_length=1)
    task: Literal['english','chinese','tags','summary','analyze','terms','calibrate']
    text: str = Field(min_length=1, max_length=60000)
    locale: Locale = 'zh'
    terminology: list[Terminology] = Field(default_factory=list, max_length=100)
