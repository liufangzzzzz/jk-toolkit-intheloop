from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response

from ...auth import require_auth
from .assets import read_asset
from .jobs import complete_job, create_job, fail_job, get_job, get_job_by_key
from .models import AgentWebsiteUrlRequest, WebsitePublishRequest
from .parser import parse_wechat_url, parse_word_file, render_preview
from .publisher import connect_fixed_account, connection_status, publish_article, recent_records

router = APIRouter(prefix="/api/v1/website-import", tags=["website-import"], dependencies=[Depends(require_auth)])
agent_router = APIRouter(prefix="/api/v1/agent/website", tags=["agent-website-import"])


def _article_payload(article) -> dict:
    return {"article": article.model_dump(), "preview_html": render_preview(article)}


def _require_agent_key(x_agent_key: str = Header("", alias="X-Agent-Key")) -> None:
    expected = os.environ.get("ITL_AGENT_API_KEY", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail={"message": "服务器尚未配置 Agent API Key"})
    if not hmac.compare_digest(x_agent_key or "", expected):
        raise HTTPException(status_code=401, detail={"message": "Agent API Key 无效"})


@router.get("/status")
async def status() -> dict:
    return connection_status()


@router.post("/connect")
async def connect() -> dict:
    try:
        return await connect_fixed_account(force=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)[:300]}) from exc


@router.post("/parse-url")
async def parse_url(body: dict) -> dict:
    source_url = str(body.get("source_url") or "").strip()
    try:
        return _article_payload(await parse_wechat_url(source_url))
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)[:500]}) from exc


@router.post("/parse-file")
async def parse_file(file: UploadFile = File(...)) -> dict:
    filename = file.filename or "document.docx"
    raw = await file.read()
    try:
        article = parse_word_file(raw, filename)
        return _article_payload(article)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)[:500]}) from exc


@router.get("/assets/{token}")
async def asset(token: str) -> Response:
    resolved = read_asset(f"ingest-asset://{token}")
    if not resolved:
        raise HTTPException(status_code=404, detail={"message": "图片不存在或已经过期"})
    raw, _filename, content_type = resolved
    return Response(content=raw, media_type=content_type)


@router.post("/publish")
async def publish(body: WebsitePublishRequest) -> dict:
    try:
        return await publish_article(
            body.article,
            mode=body.mode,
            column_id=body.column_id,
            request_id=body.request_id,
        )
    except Exception as exc:
        action = "发布" if body.mode == "publish" else "创建草稿"
        raise HTTPException(status_code=502, detail={"message": f"官网{action}失败：{str(exc)[:500]}"}) from exc


@router.get("/history")
async def history(limit: int = 10) -> dict:
    return {"records": recent_records(limit)}


@agent_router.post("/import-url", dependencies=[Depends(_require_agent_key)])
async def agent_import_url(body: AgentWebsiteUrlRequest) -> dict:
    existing = get_job_by_key(body.idempotency_key)
    if existing:
        return existing
    job = create_job(body.idempotency_key, "wechat_url", body.model_dump())
    try:
        article = await parse_wechat_url(body.source_url)
        if body.tags:
            article.tags = list(dict.fromkeys([*article.tags, *body.tags]))[:10]
        result = await publish_article(
            article,
            mode=body.mode,
            column_id=body.column_id,
            request_id=f"agent:{body.idempotency_key}",
        )
        return complete_job(job["id"], result)
    except Exception as exc:
        failed = fail_job(job["id"], str(exc))
        raise HTTPException(status_code=502, detail={"message": str(exc)[:500], "job": failed}) from exc


@agent_router.post("/import-file", dependencies=[Depends(_require_agent_key)])
async def agent_import_file(
    file: UploadFile = File(...),
    idempotency_key: str = Form(...),
    mode: str = Form("draft"),
    column_id: int | None = Form(None),
    tags: str = Form(""),
) -> dict:
    if mode not in {"draft", "publish"}:
        raise HTTPException(status_code=400, detail={"message": "mode 只能是 draft 或 publish"})
    existing = get_job_by_key(idempotency_key)
    if existing:
        return existing
    filename = file.filename or "document.docx"
    job = create_job(
        idempotency_key,
        "word",
        {"filename": filename, "mode": mode, "column_id": column_id, "tags": tags},
    )
    try:
        article = parse_word_file(await file.read(), filename)
        extra_tags = [item.strip() for item in tags.split(",") if item.strip()]
        article.tags = list(dict.fromkeys([*article.tags, *extra_tags]))[:10]
        result = await publish_article(
            article,
            mode=mode,
            column_id=column_id,
            request_id=f"agent:{idempotency_key}",
        )
        return complete_job(job["id"], result)
    except Exception as exc:
        failed = fail_job(job["id"], str(exc))
        raise HTTPException(status_code=502, detail={"message": str(exc)[:500], "job": failed}) from exc


@agent_router.get("/jobs/{job_id}", dependencies=[Depends(_require_agent_key)])
async def agent_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"message": "任务不存在"})
    return job
