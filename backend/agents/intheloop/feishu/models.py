"""飞书云文档统一引用（解析 API 入参）。"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

ExportObjType = Literal["docx", "doc"]
LinkSource = Literal["docx", "doc", "wiki", "file"]


class CloudDocRef(BaseModel):
    """经链接解析 +（wiki 时）节点查询后的可解析文档引用。"""

    source: LinkSource
    obj_token: str = Field(..., description="飞书文档 API 使用的 token")
    obj_type: ExportObjType
    node_token: Optional[str] = None
    title: Optional[str] = None
