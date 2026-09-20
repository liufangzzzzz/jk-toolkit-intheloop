"""飞书分享链接 → CloudDocRef（docx / doc / wiki / file）。"""
from __future__ import annotations

import re
from typing import Optional, Tuple
from urllib.parse import unquote, urlparse

from .client import FeishuApiClient
from .errors import FEISHU_LINK_INVALID, FEISHU_UNSUPPORTED_TYPE, FeishuServiceError
from .models import CloudDocRef, ExportObjType

# 新版文档、旧版文档、知识库（含 larkoffice 国际域）
_RE_DOCX = re.compile(r"^/docx/([^/?#]+)", re.I)
_RE_DOCS = re.compile(r"^/(?:docs|doc)/([^/?#]+)", re.I)
_RE_WIKI = re.compile(r"^/wiki/([^/?#]+)", re.I)
_RE_FILE = re.compile(r"^/file/([^/?#]+)", re.I)

_EXPORTABLE = frozenset({"docx", "doc"})


def _normalize_url(url: str) -> str:
    u = url.strip()
    if not u:
        return u
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


def parse_link_shape(url: str) -> Tuple[str, str]:
    """
    解析 URL 路径形态，不调用 API。
    返回 (kind, token)，kind ∈ docx|doc|wiki|file。
    """
    normalized = _normalize_url(url)
    parsed = urlparse(normalized)
    path = unquote(parsed.path or "")

    for regex, kind in (
        (_RE_DOCX, "docx"),
        (_RE_DOCS, "doc"),
        (_RE_WIKI, "wiki"),
        (_RE_FILE, "file"),
    ):
        m = regex.search(path)
        if m:
            return kind, m.group(1)
    raise FeishuServiceError(
        "无法识别的飞书链接：请使用 /docx/、/docs/、/wiki/ 或 /file/ 标准分享链接",
        FEISHU_LINK_INVALID,
    )


async def resolve_cloud_doc_ref(url: str, client: FeishuApiClient) -> CloudDocRef:
    """链接 → 可导出 CloudDocRef（wiki 会调 get_node）。"""
    kind, token = parse_link_shape(url)

    if kind == "docx":
        return CloudDocRef(source="docx", obj_token=token, obj_type="docx")
    if kind == "doc":
        return CloudDocRef(source="doc", obj_token=token, obj_type="doc")

    if kind == "wiki":
        node = await client.get_wiki_node(token)
        obj_token = node.get("obj_token") or ""
        obj_type = (node.get("obj_type") or "").lower()
        title = node.get("title")
        if obj_type not in _EXPORTABLE:
            raise FeishuServiceError(
                f"知识库节点类型「{obj_type or '未知'}」不支持排版，仅支持 docx/doc 文档页",
                FEISHU_UNSUPPORTED_TYPE,
            )
        return CloudDocRef(
            source="wiki",
            obj_token=obj_token,
            obj_type=obj_type,  # type: ignore[arg-type]
            node_token=token,
            title=title,
        )

    # /file/{token}：batch_query 探测 docx / doc
    return await _resolve_file_token(token, client)


async def _resolve_file_token(file_token: str, client: FeishuApiClient) -> CloudDocRef:
    for doc_type in ("docx", "doc"):
        meta = await client.batch_query_meta(file_token, doc_type)
        if meta:
            title = meta.get("title")
            return CloudDocRef(
                source="file",
                obj_token=file_token,
                obj_type=doc_type,  # type: ignore[arg-type]
                title=title,
            )
    raise FeishuServiceError(
        "云空间文件链接无法解析为可导出的飞书文档（仅支持文档类 file/docx/doc）",
        FEISHU_UNSUPPORTED_TYPE,
    )


def suggested_filename(ref: CloudDocRef, override: Optional[str] = None) -> str:
    if override:
        name = override.strip()
        if not name.lower().endswith(".docx"):
            name += ".docx"
        return name
    base = (ref.title or "feishu-document").strip() or "feishu-document"
    for ch in '<>:"/\\|?*':
        base = base.replace(ch, "_")
    if not base.lower().endswith(".docx"):
        base += ".docx"
    return base
