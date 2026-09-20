from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from agents.intheloop.feishu.errors import FeishuServiceError
from agents.intheloop.feishu_parser import parse_feishu_document
from agents.intheloop.renderer import render_intheloop_html
from agents.intheloop.schema import InTheLoopArticle
from agents.intheloop.wechat.config import WeChatConfig
from agents.intheloop.wechat.service import WeChatDraftService

from ...database import database
from ...settings_store import load_settings, update_settings

DEFAULT_WECHAT_APP_ID = "wx0ad9c0e3d4f70a6c"


def public_settings() -> dict[str, Any]:
    wechat = load_settings().get("wechat") or {}
    return {
        "app_id": wechat.get("app_id") or os.environ.get("WECHAT_APP_ID") or DEFAULT_WECHAT_APP_ID,
        "has_secret": bool(wechat.get("app_secret") or os.environ.get("WECHAT_APP_SECRET")),
        "account_name": wechat.get("account_name") or os.environ.get("WECHAT_ACCOUNT_NAME", "In The Loop.具身现场"),
        "tested": bool(wechat.get("tested")),
    }


def save_settings(*, app_id: str, app_secret: str, account_name: str) -> dict[str, Any]:
    current = load_settings().get("wechat") or {}
    secret = app_secret.strip() or str(current.get("app_secret") or os.environ.get("WECHAT_APP_SECRET", ""))
    if not secret:
        raise ValueError("请输入 AppSecret")
    update_settings(
        "wechat",
        app_id=app_id.strip(),
        app_secret=secret,
        account_name=account_name.strip() or "In The Loop.具身现场",
        tested=False,
    )
    return public_settings()


def _config() -> WeChatConfig:
    saved = load_settings().get("wechat") or {}
    app_id = str(saved.get("app_id") or os.environ.get("WECHAT_APP_ID") or DEFAULT_WECHAT_APP_ID).strip()
    app_secret = str(saved.get("app_secret") or os.environ.get("WECHAT_APP_SECRET", "")).strip()
    if not app_id or not app_secret:
        raise ValueError("微信公众号尚未配置")
    return WeChatConfig(
        app_id=app_id,
        app_secret=app_secret,
        upload_mode="real",
        api_base=os.environ.get("WECHAT_API_BASE", "https://api.weixin.qq.com/cgi-bin").rstrip("/"),
        account_label=str(saved.get("account_name") or os.environ.get("WECHAT_ACCOUNT_NAME", "In The Loop.具身现场")),
        thumb_media_id=os.environ.get("WECHAT_THUMB_MEDIA_ID") or None,
        default_cover_image_path=os.environ.get("WECHAT_DEFAULT_COVER_IMAGE_PATH") or None,
        account_id="intheloop",
    )


async def test_connection() -> str:
    try:
        await asyncio.to_thread(WeChatDraftService(_config())._client.get_access_token, force=True)
    except Exception:
        update_settings("wechat", tested=False)
        raise
    update_settings("wechat", tested=True)
    return "微信公众号连接成功"


async def parse_source(feishu_url: str) -> dict[str, Any]:
    try:
        article = await parse_feishu_document(feishu_url.strip())
    except FeishuServiceError:
        raise
    return {
        "article": article.model_dump(),
        "preview_html": render_intheloop_html(article, preview=True),
        "stats": {
            "heading_count": article.heading_count,
            "image_count": article.image_count,
            "video_count": article.video_count,
        },
        "warnings": article.warnings,
    }


def _existing_result(request_id: str) -> dict[str, Any] | None:
    if not request_id:
        return None
    with database() as connection:
        row = connection.execute(
            """
            SELECT external_id, warnings_json
            FROM publish_records
            WHERE request_id = ? AND destination = 'wechat'
            """,
            (request_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "ok": True,
        "media_id": row["external_id"],
        "warnings": json.loads(row["warnings_json"] or "[]"),
        "duplicate_prevented": True,
    }


async def create_draft(
    article: InTheLoopArticle,
    *,
    request_id: str,
    source_ref: str,
) -> dict[str, Any]:
    existing = _existing_result(request_id)
    if existing:
        return existing
    if not public_settings()["tested"] and not os.environ.get("WECHAT_APP_ID"):
        raise ValueError("请先完成微信公众号连接检测")
    registry = [
        {"block_id": block.source_block_id, "image_url": block.url, "label_zh": "正文图片"}
        for block in article.blocks
        if block.type == "image" and block.url
    ]
    result = await asyncio.to_thread(
        WeChatDraftService(_config()).create_draft_from_html,
        title=article.title,
        author=article.author or "In The Loop",
        digest=article.digest,
        html=render_intheloop_html(article),
        figure_registry=registry,
        source_channel="feishu",
        skip_cover=False,
    )
    warnings = [f"{item.module}：{item.message}" for item in result.failures]
    with database() as connection:
        connection.execute(
            """
            INSERT INTO publish_records(
                request_id, destination, source_type, source_ref, title,
                external_id, state, warnings_json
            ) VALUES (?, 'wechat', 'feishu', ?, ?, ?, 'draft', ?)
            """,
            (request_id or None, source_ref, article.title, result.media_id, json.dumps(warnings, ensure_ascii=False)),
        )
    return {
        "ok": True,
        "media_id": result.media_id,
        "warnings": warnings,
        "duplicate_prevented": False,
    }


def recent_records(limit: int = 10) -> list[dict[str, Any]]:
    with database() as connection:
        rows = connection.execute(
            """
            SELECT id, title, external_id, state, created_at, warnings_json
            FROM publish_records
            WHERE destination = 'wechat'
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 50)),),
        ).fetchall()
    return [
        {
            **{key: row[key] for key in ("id", "title", "external_id", "state", "created_at")},
            "warnings": json.loads(row["warnings_json"] or "[]"),
        }
        for row in rows
    ]
