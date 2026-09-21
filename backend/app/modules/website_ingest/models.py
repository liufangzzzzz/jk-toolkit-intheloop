from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class WebsiteImageIssue(BaseModel):
    index: int = Field(ge=1)
    label: str = ""
    source_url: str = ""
    asset_url: str = ""
    message: str


class WebsiteImportArticle(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    abstract: str = Field(default="", max_length=500)
    content_html: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    cover_asset: str = ""
    source_type: Literal["wechat_url", "docx", "doc"]
    source_ref: str = ""
    warnings: list[str] = Field(default_factory=list)
    image_issues: list[WebsiteImageIssue] = Field(default_factory=list)


class WebsitePublishRequest(BaseModel):
    article: WebsiteImportArticle
    mode: Literal["draft", "publish"] = "draft"
    column_id: int | None = None
    request_id: str = Field(min_length=1, max_length=160)


class AgentWebsiteUrlRequest(BaseModel):
    source_url: str = Field(min_length=1)
    mode: Literal["draft", "publish"] = "draft"
    column_id: int | None = None
    tags: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1, max_length=160)
