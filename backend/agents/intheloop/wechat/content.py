"""正文 HTML 与 figure_registry 图片处理。"""
from __future__ import annotations

import base64
import logging
import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
import mimetypes

import httpx

_DATA_URL_RE = re.compile(
    r"^data:image/(?P<fmt>png|jpe?g|gif);base64,(?P<data>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_IMG_SRC_RE = re.compile(
    r'(<img\b[^>]*\bsrc=["\'])([^"\']+)(["\'])',
    re.IGNORECASE,
)
_PLAIN_WS_RE = re.compile(r"\s+")

logger = logging.getLogger(__name__)

# 微信公众平台草稿 news 字段上限（与产品口径一致）
WECHAT_TITLE_MAX_LEN = 64
WECHAT_DIGEST_MAX_LEN = 120
WECHAT_AUTHOR_MAX_LEN = 16


def _content_char_limit() -> int:
    """
    正文 HTML 可选上限（字符数）。默认 **不截断**，完整上传层4 排版结果。

    仅当设置环境变量 ``WECHAT_DRAFT_CONTENT_MAX_CHARS`` 为正整数时才会在
    调用 draft/add 前裁剪正文；设为 ``0`` 或未设置均表示不限制。
    若超过微信公众平台实际限制，由微信 API 返回错误（不静默丢稿尾）。
    """
    raw = os.environ.get("WECHAT_DRAFT_CONTENT_MAX_CHARS", "0")
    try:
        limit = int(raw)
    except ValueError:
        return 0
    return max(0, min(limit, 2_000_000))


def parse_data_url(url: str) -> Optional[Tuple[bytes, str]]:
    """解析 data:image/...;base64,... → (bytes, filename_hint)。"""
    m = _DATA_URL_RE.match((url or "").strip())
    if not m:
        return None
    fmt = m.group("fmt").lower()
    ext = "jpg" if fmt in ("jpeg", "jpg") else fmt
    try:
        raw = base64.b64decode(m.group("data"), validate=False)
    except Exception:
        return None
    if not raw:
        return None
    return raw, f"image.{ext}"


def collect_registry_image_bytes(
    registry: List[dict],
) -> List[Tuple[str, bytes, str]]:
    """按 registry 顺序收集可上传图片字节。返回 (block_id, bytes, filename)。"""
    out: List[Tuple[str, bytes, str]] = []
    for ent in registry or []:
        url = ent.get("image_url") or ""
        parsed = parse_data_url(url)
        if not parsed:
            continue
        data, fname = parsed
        out.append((str(ent.get("block_id", "")), data, fname))
    return out


def fetch_image_bytes_from_url(url: str, timeout_s: float = 20.0) -> Optional[Tuple[bytes, str]]:
    """下载 http(s) 图片，返回 (bytes, filename)。"""
    src = (url or "").strip()
    if not src.startswith(("http://", "https://")):
        return None
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
            resp = client.get(src)
        if resp.status_code != 200 or not resp.content:
            return None
        ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
        parsed = urlparse(src)
        name = (parsed.path.rsplit("/", 1)[-1] or "").strip()
        ext = ""
        if "." in name:
            ext = name.rsplit(".", 1)[-1].lower()
        if not ext:
            guessed = mimetypes.guess_extension(ctype) if ctype else None
            ext = (guessed or ".jpg").lstrip(".")
        if ext == "jpeg":
            ext = "jpg"
        fname = f"image.{ext}"
        return resp.content, fname
    except Exception:
        return None


def rewrite_html_image_src(html: str, url_map: Dict[str, str]) -> str:
    """将 HTML 中 img src 按 url_map 替换（键为原 src）。"""

    def _repl(m: re.Match[str]) -> str:
        old = m.group(2)
        new = url_map.get(old, old)
        return f"{m.group(1)}{new}{m.group(3)}"

    return _IMG_SRC_RE.sub(_repl, html or "")


def truncate_wechat_fields(
    title: str,
    author: str,
    digest: str,
    content: str,
) -> Tuple[str, str, str, str]:
    """微信草稿字段终检：标题/作者/摘要按公众平台字段上限裁剪；正文默认不裁剪。"""
    t = normalize_plain_text(title or "") or "（无标题）"
    t = t[:WECHAT_TITLE_MAX_LEN]
    a = normalize_plain_text(author or "")[:WECHAT_AUTHOR_MAX_LEN]
    d = normalize_plain_text(digest or "")[:WECHAT_DIGEST_MAX_LEN]
    c = content or ""
    limit = _content_char_limit()
    if limit > 0 and len(c) > limit:
        logger.warning(
            "微信公众号正文超长，已按阈值截断",
            extra={"raw_len": len(c), "limit": limit},
        )
        c = c[:limit]
    return t, a, d, c


def normalize_plain_text(text: str) -> str:
    """Small InTheLoop-owned plain-text normalizer for WeChat fields."""
    s = str(text or "").replace("\u200b", "").replace("\ufeff", "")
    s = s.replace("\u00a0", " ").strip()
    return _PLAIN_WS_RE.sub(" ", s)
