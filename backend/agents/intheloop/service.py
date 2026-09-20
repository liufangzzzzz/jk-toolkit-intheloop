"""InTheLoop orchestration: parse session cache + WeChat draft caller."""
from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from typing import Dict, Optional

from agents.intheloop.feishu_parser import parse_feishu_document
from agents.intheloop.renderer import render_intheloop_html
from agents.intheloop.schema import InTheLoopArticle

_SESSION_TTL_SECONDS = 30 * 60
_CACHE_LOCK = threading.Lock()
_SESSIONS: Dict[str, "_InTheLoopParseSession"] = {}


def _real_draft_upload_allowed() -> bool:
    raw = os.environ.get("INTHELOOP_ALLOW_REAL_DRAFT_UPLOAD", "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


class InTheLoopSessionExpiredError(ValueError):
    pass


class InTheLoopRealUploadNotReadyError(ValueError):
    pass


class _InTheLoopParseSession:
    def __init__(
        self,
        *,
        parse_id: str,
        article: InTheLoopArticle,
        preview_html: str,
    ) -> None:
        self.parse_id = parse_id
        self.article = article
        self.preview_html = preview_html
        self.created_at = time.time()

    @property
    def expired(self) -> bool:
        return time.time() - self.created_at > _SESSION_TTL_SECONDS


def _store_session(session: _InTheLoopParseSession) -> None:
    now = time.time()
    with _CACHE_LOCK:
        _SESSIONS[session.parse_id] = session
        expired = [
            pid
            for pid, item in _SESSIONS.items()
            if now - item.created_at > _SESSION_TTL_SECONDS
        ]
        for pid in expired:
            _SESSIONS.pop(pid, None)


def get_parse_session(parse_id: str) -> _InTheLoopParseSession:
    with _CACHE_LOCK:
        item = _SESSIONS.get((parse_id or "").strip())
        if item is None:
            raise InTheLoopSessionExpiredError("parse_id 不存在或已过期，请重新解析")
        if item.expired:
            _SESSIONS.pop(item.parse_id, None)
            raise InTheLoopSessionExpiredError("parse_id 不存在或已过期，请重新解析")
        return item


async def parse_intheloop_url(feishu_url: str) -> dict:
    """Fetch, parse, render preview and create a short-lived parse session."""
    article = await parse_feishu_document(feishu_url)
    preview_html = render_intheloop_html(article, preview=True)
    parse_id = f"intheloop-{uuid.uuid4().hex[:12]}"
    _store_session(
        _InTheLoopParseSession(
            parse_id=parse_id,
            article=article,
            preview_html=preview_html,
        )
    )
    return {
        "parse_id": parse_id,
        "title": article.title,
        "author": article.author,
        "editor": article.editor,
        "digest": article.digest,
        "heading_count": article.heading_count,
        "image_count": article.image_count,
        "video_count": article.video_count,
        "preview_html": preview_html,
        "warnings": list(article.warnings),
    }


async def upload_intheloop_draft(parse_id: str, account_id: str) -> dict:
    """Upload the confirmed parsed article to WeChat drafts only."""
    session = get_parse_session(parse_id)
    account_id = (account_id or "").strip()

    from agents.intheloop.wechat import get_wechat_draft_service
    from agents.intheloop.wechat.config import get_wechat_upload_mode
    from agents.intheloop.wechat_accounts import assert_intheloop_account_selectable

    assert_intheloop_account_selectable(account_id)
    upload_mode = get_wechat_upload_mode()
    if upload_mode == "real" and not _real_draft_upload_allowed():
        raise InTheLoopRealUploadNotReadyError(
            "InTheLoop 真实微信草稿上传尚未开启："
            "请明确确认后设置 INTHELOOP_ALLOW_REAL_DRAFT_UPLOAD=true 再上传"
        )

    article = session.article
    final_html = render_intheloop_html(article)

    if upload_mode != "real":
        import datetime

        media_id = f"stub_intheloop_{datetime.datetime.now():%Y%m%d%H%M%S}"
        return {
            "ok": True,
            "media_id": media_id,
            "upload_mode": upload_mode,
            "message": "stub 模式：未调用微信草稿 API",
            "warnings": [],
        }

    svc = get_wechat_draft_service(account_id)

    def _upload() -> object:
        return svc.create_draft_from_html(
            title=article.title,
            author=article.author or "In The Loop",
            digest=article.digest,
            html=final_html,
            figure_registry=[],
            source_channel="feishu",
            skip_cover=True,
        )

    result = await asyncio.to_thread(_upload)
    warnings = [
        f"{item.module}: {item.message}"
        for item in getattr(result, "failures", []) or []
    ]
    return {
        "ok": True,
        "media_id": getattr(result, "media_id", ""),
        "upload_mode": upload_mode,
        "message": "公众号草稿已创建",
        "warnings": warnings,
    }
