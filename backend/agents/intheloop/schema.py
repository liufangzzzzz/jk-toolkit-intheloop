"""InTheLoop domain schema for deterministic Feishu parsing and rendering."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

InTheLoopBlockType = Literal[
    "paragraph",
    "heading",
    "question",
    "answer",
    "image",
    "caption",
    "file",
]


class InTheLoopBlock(BaseModel):
    type: InTheLoopBlockType
    content: str = ""
    speaker: str = ""
    url: Optional[str] = None
    caption: Optional[str] = None
    source_block_id: str = ""


class InTheLoopArticle(BaseModel):
    title: str = ""
    author: str = ""
    editor: str = ""
    digest: str = ""
    header_source: str = ""
    blocks: List[InTheLoopBlock] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    video_count: int = 0
    attachment_count: int = 0

    @property
    def heading_count(self) -> int:
        return sum(1 for block in self.blocks if block.type == "heading")

    @property
    def image_count(self) -> int:
        return sum(1 for block in self.blocks if block.type == "image")
