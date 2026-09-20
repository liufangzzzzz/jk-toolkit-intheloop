"""飞书链接统一校验入口。"""
from __future__ import annotations

from .link_resolver import parse_link_shape


def validate_feishu_url(url: str) -> str:
    """校验飞书链接并返回去空白后的 URL。

    统一支持：/docx/、/docs|/doc/、/wiki/、/file/。
    异常统一抛出 FeishuServiceError（含 FEISHU_* error_code）。
    """
    normalized = (url or "").strip()
    parse_link_shape(normalized)
    return normalized

