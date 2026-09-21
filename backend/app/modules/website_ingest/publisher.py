from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from ...database import database
from ...geekpark_auth import list_geekpark_columns, login_geekpark
from ...settings_store import load_settings, update_settings
from .assets import read_asset
from .models import WebsiteImportArticle
from .parser import sanitize_fragment

_ASSET_RE = re.compile(r"ingest-asset://[a-f0-9]{32}\.[a-z0-9]{1,8}")


def _industry_column_id(columns: list[dict[str, Any]]) -> int:
    exact = next((item for item in columns if str(item.get("title") or "").strip() == "行业资讯"), None)
    partial = next((item for item in columns if "行业资讯" in str(item.get("title") or "")), None)
    candidate = exact or partial
    if candidate:
        return int(candidate.get("id") or 0)
    if any(int(item.get("id") or 0) == 2 for item in columns):
        return 2
    return 0


def connection_status() -> dict[str, Any]:
    website = load_settings().get("website") or {}
    fixed_credentials = bool(
        os.environ.get("GEEKPARK_LOGIN_NAME", "").strip()
        and os.environ.get("GEEKPARK_LOGIN_PASSWORD", "")
    )
    return {
        "connected": bool(website.get("access_key")),
        "fixed_credentials": fixed_credentials,
        "nickname": website.get("nickname", ""),
        "author_id": website.get("author_id"),
        "column_id": int(website.get("column_id") or 0),
        "columns": website.get("columns") or [],
    }


async def connect_fixed_account(*, force: bool = False) -> dict[str, Any]:
    status = connection_status()
    if status["connected"] and not force:
        return status
    login_name = os.environ.get("GEEKPARK_LOGIN_NAME", "").strip()
    password = os.environ.get("GEEKPARK_LOGIN_PASSWORD", "")
    if not login_name or not password:
        if status["connected"]:
            return status
        raise ValueError("服务器尚未配置固定的极客公园官网账号和密码")
    result = await login_geekpark(login_name, password)
    columns = await list_geekpark_columns()
    current = load_settings().get("website") or {}
    current_column = int(current.get("column_id") or 0)
    valid_ids = {int(item["id"]) for item in columns}
    if current_column not in valid_ids:
        current_column = _industry_column_id(columns) or (int(columns[0]["id"]) if columns else 0)
    update_settings(
        "website",
        access_key=result.access_key,
        nickname=result.nickname,
        author_id=result.author_id,
        columns=columns,
        column_id=current_column,
        tested=True,
    )
    return connection_status()


async def _upload_image(reference: str, access_key: str) -> dict[str, Any]:
    asset = read_asset(reference)
    if not asset:
        raise RuntimeError("有一张待上传图片已过期，请重新解析来源")
    raw, filename, content_type = asset
    base = os.environ.get("WEBSITE_GEEKPARK_API_BASE", "https://mainssl.geekpark.net").rstrip("/")
    roles = os.environ.get("WEBSITE_GEEKPARK_ROLES", "dev").strip()
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{base}/api/v1/admin/images",
            params={"roles": roles, "access_key": access_key},
            files={"upload_file": (filename, raw, content_type)},
        )
    if response.status_code in {401, 403}:
        raise PermissionError("官网登录已过期")
    if response.status_code not in {200, 201}:
        raise RuntimeError(f"官网图片上传失败（HTTP {response.status_code}）")
    payload = response.json()
    image = payload.get("image") or payload
    url = str(image.get("url") or "").replace("http://", "https://", 1)
    if not url:
        raise RuntimeError("官网图片上传响应缺少 URL")
    return {"url": url, "id": image.get("id") or ""}


async def _prepare_images(
    article: WebsiteImportArticle,
    access_key: str,
) -> tuple[str, dict[str, Any], list[str], list[dict[str, Any]]]:
    warnings = list(article.warnings)
    references = list(dict.fromkeys(_ASSET_RE.findall(article.content_html)))
    if article.cover_asset and article.cover_asset not in references:
        references.insert(0, article.cover_asset)
    uploaded: dict[str, dict[str, Any]] = {}
    failed_images: list[dict[str, Any]] = []
    for index, reference in enumerate(references, start=1):
        try:
            uploaded[reference] = await _upload_image(reference, access_key)
        except PermissionError:
            raise
        except Exception as exc:
            token = reference.removeprefix("ingest-asset://")
            message = str(exc)[:180] or "官网图片上传失败"
            failed_images.append({
                "index": index,
                "label": f"第 {index} 张图片",
                "asset_url": f"/api/v1/website-import/assets/{token}?download=true",
                "message": message,
            })
            warnings.append(f"第 {index} 张图片上传失败：{message}；可下载原图后在官网后台手动补回")
    content = article.content_html
    for reference, image in uploaded.items():
        content = content.replace(reference, image["url"])
    soup = BeautifulSoup(content, "html.parser")
    for image in soup.find_all("img"):
        if str(image.get("src") or "").startswith("ingest-asset://"):
            image.decompose()
    cover = uploaded.get(article.cover_asset) if article.cover_asset else None
    if not cover:
        first_reference = next((reference for reference in references if reference in uploaded), "")
        cover = uploaded.get(first_reference) if first_reference else None
    if not cover:
        warnings.append("来源中没有可用图片，官网文章未自动设置头图")
    return str(soup), cover or {"url": "", "id": ""}, warnings, failed_images


def _existing_result(request_id: str) -> dict[str, Any] | None:
    with database() as connection:
        row = connection.execute(
            """
            SELECT external_id, external_url, admin_url, state, warnings_json
            FROM publish_records
            WHERE request_id = ? AND destination = 'website'
            """,
            (request_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "ok": True,
        "article_id": row["external_id"],
        "public_url": row["external_url"],
        "admin_edit_url": row["admin_url"],
        "state": row["state"],
        "warnings": json.loads(row["warnings_json"] or "[]"),
        "failed_images": [],
        "duplicate_prevented": True,
    }


async def _post_article(payload: dict[str, Any], access_key: str) -> httpx.Response:
    base = os.environ.get("WEBSITE_GEEKPARK_API_BASE", "https://mainssl.geekpark.net").rstrip("/")
    roles = os.environ.get("WEBSITE_GEEKPARK_ROLES", "dev").strip()
    async with httpx.AsyncClient(timeout=60) as client:
        return await client.post(
            f"{base}/api/v1/admin/posts",
            params={"roles": roles, "access_key": access_key},
            json=payload,
            headers={"content-type": "application/json; charset=utf-8"},
        )


async def publish_article(
    article: WebsiteImportArticle,
    *,
    mode: str,
    column_id: int | None,
    request_id: str,
) -> dict[str, Any]:
    existing = _existing_result(request_id)
    if existing:
        return existing
    await connect_fixed_account()
    saved = load_settings().get("website") or {}
    access_key = str(saved.get("access_key") or "").strip()
    author_id = saved.get("author_id")
    if not access_key or author_id is None:
        raise RuntimeError("官网账号尚未连接")
    article = article.model_copy(update={"content_html": sanitize_fragment(article.content_html)})
    try:
        content, cover, warnings, failed_images = await _prepare_images(article, access_key)
    except PermissionError:
        if not connection_status()["fixed_credentials"]:
            raise
        await connect_fixed_account(force=True)
        saved = load_settings().get("website") or {}
        access_key = str(saved.get("access_key") or "").strip()
        author_id = saved.get("author_id")
        content, cover, warnings, failed_images = await _prepare_images(article, access_key)
    columns = saved.get("columns") or []
    default_column = _industry_column_id(columns) if article.source_type in {"doc", "docx"} else 0
    resolved_column = int(column_id or default_column or saved.get("column_id") or 0)
    state = "published" if mode == "publish" else "unpublished"
    payload = {
        "content_type": "html",
        "content_source": content,
        "title": article.title,
        "abstract": article.abstract,
        "tags": list(dict.fromkeys(tag.strip() for tag in article.tags if tag.strip()))[:10],
        "column_id": resolved_column,
        "authors": [author_id],
        "state": state,
        "post_type": "text",
    }
    if cover.get("id") and cover.get("url"):
        payload["cover_id"] = cover["id"]
        payload["cover_url"] = cover["url"]
    response = await _post_article(payload, access_key)
    if response.status_code in {401, 403} and connection_status()["fixed_credentials"]:
        await connect_fixed_account(force=True)
        saved = load_settings().get("website") or {}
        access_key = str(saved.get("access_key") or "").strip()
        payload["authors"] = [saved.get("author_id")]
        response = await _post_article(payload, access_key)
    if response.status_code not in {200, 201}:
        detail = response.text[:300]
        raise RuntimeError(f"官网{'发布' if mode == 'publish' else '草稿创建'}失败（HTTP {response.status_code}）：{detail}")
    result = response.json()
    result_post = result.get("post") if isinstance(result.get("post"), dict) else {}
    article_id = result.get("id") or result_post.get("id")
    if article_id is None:
        raise RuntimeError("官网响应缺少文章 ID")
    admin_base = os.environ.get("WEBSITE_GEEKPARK_ADMIN_BASE", "https://admin.geekpark.net").rstrip("/")
    admin_url = f"{admin_base}/posts/new?id={article_id}"
    public_base = os.environ.get("WEBSITE_GEEKPARK_PUBLIC_BASE", "https://www.geekpark.net").rstrip("/")
    public_url = f"{public_base}/news/{article_id}" if mode == "publish" else ""
    with database() as connection:
        connection.execute(
            """
            INSERT INTO publish_records(
                request_id, destination, source_type, source_ref, title,
                external_id, external_url, admin_url, state, warnings_json
            ) VALUES (?, 'website', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                article.source_type,
                article.source_ref,
                article.title,
                str(article_id),
                public_url,
                admin_url,
                state,
                json.dumps(warnings, ensure_ascii=False),
            ),
        )
    return {
        "ok": True,
        "article_id": article_id,
        "public_url": public_url,
        "admin_edit_url": admin_url,
        "state": state,
        "warnings": warnings,
        "failed_images": failed_images,
        "duplicate_prevented": False,
    }


def recent_records(limit: int = 10) -> list[dict[str, Any]]:
    with database() as connection:
        rows = connection.execute(
            """
            SELECT id, title, source_type, external_id, external_url, admin_url, state, created_at, warnings_json
            FROM publish_records
            WHERE destination = 'website'
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 50)),),
        ).fetchall()
    return [
        {
            **{key: row[key] for key in ("id", "title", "source_type", "external_id", "external_url", "admin_url", "state", "created_at")},
            "warnings": json.loads(row["warnings_json"] or "[]"),
        }
        for row in rows
    ]
