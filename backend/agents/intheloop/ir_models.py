"""Minimal document IR models owned by InTheLoop."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EmphasisSpan(BaseModel):
    text: str = ""
    bold: bool = False
    italic: bool = False


class RawBlock(BaseModel):
    block_id: str = ""
    block_type: str = "paragraph"
    text: str = ""
    image_url: Optional[str] = None
    bold: bool = False
    italic: bool = False
    align: str = "left"
    indent_level: int = 0
    is_empty: bool = False
    original_tag: Optional[str] = None
    emphasis_spans: List[EmphasisSpan] = Field(default_factory=list)
    extra: Dict[str, Any] = Field(default_factory=dict)


class WordParseResult(BaseModel):
    source: str = ""
    filename: str = ""
    document_title: str = ""
    raw_block_list: List[RawBlock] = Field(default_factory=list)
    mammoth_messages: List[str] = Field(default_factory=list)
