from datetime import date
from typing import Literal
from urllib.parse import urlparse
from pydantic import BaseModel, Field, field_validator, model_validator

Locale = Literal['zh', 'en']

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

class Tag(Base):
    tag_type: Literal["topic","company","product"] = "topic"
    map_level: Literal["primary","medium","secondary"] = "secondary"
    aliases: list[str] = Field(default_factory=list)
    website: str = ""

    @field_validator("website")
    @classmethod
    def check_website(cls, value): return valid_url(value)

    map_visible: bool = True
    parent_ids: list[str] = Field(default_factory=list)
    related_tag_ids: list[str] = Field(default_factory=list)
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

class ImportURL(BaseModel):
    url: str = Field(min_length=1, max_length=4000)

class Version(BaseModel):
    title: str = Field(default='', max_length=250)
    summary: str = ''
    body: str = ''
    destination: Literal['hosted','external'] = 'hosted'
    external_url: str = ''
    platform: str = ''
    links: list[Resource] = Field(default_factory=list)

    @field_validator('external_url')
    @classmethod
    def url(cls, value): return valid_url(value)

class Content(Base):
    source_account: str = Field(default='', max_length=180)
    @model_validator(mode='before')
    @classmethod
    def defaults(cls, value):
        if isinstance(value,dict):
            value = dict(value)
            if not value.get('brand'):
                value['brand'] = 'linkstart' if value.get('kind')=='podcast' else 'intheloop'
            host = urlparse(str(value.get('source_url') or '')).hostname or ''
            if host == 'xiaoyuzhoufm.com' or host.endswith('.xiaoyuzhoufm.com'):
                value['chinese_only'] = True
        return value

    chinese_only: bool = False
    brand: Literal["geekpark","intheloop","linkstart"] = "intheloop"
    resources: list[Companion] = Field(default_factory=list)
    kind: Literal['article','podcast','link'] = 'article'
    section: Literal['reporting','overseas'] = 'reporting'
    source_url: str = ''
    date: date
    audio_language: Locale = 'zh'
    guests: str = ''
    duration: str = ''
    company_ids: list[str] = Field(default_factory=list)
    tag_ids: list[str] = Field(default_factory=list)
    versions: dict[Locale, Version]

    @field_validator('source_url')
    @classmethod
    def url(cls, value): return valid_url(value)

class Publication(BaseModel):
    locale: Locale
    revision: int

class Generate(BaseModel):
    model: str = Field(min_length=1)
    task: Literal['english','tags','summary']
    text: str = Field(min_length=1, max_length=60000)
