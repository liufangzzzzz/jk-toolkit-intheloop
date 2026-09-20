from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agents.intheloop.schema import InTheLoopArticle

from ...auth import require_auth
from .service import (
    create_draft,
    parse_source,
    public_settings,
    recent_records,
    save_settings,
    test_connection,
)

router = APIRouter(prefix="/api/v1/wechat-draft", tags=["wechat-draft"], dependencies=[Depends(require_auth)])


class SettingsRequest(BaseModel):
    app_id: str = Field(min_length=1)
    app_secret: str = ""
    account_name: str = "In The Loop.具身现场"


class ParseRequest(BaseModel):
    feishu_url: str = Field(min_length=1)


class PublishRequest(BaseModel):
    article: InTheLoopArticle
    request_id: str = Field(min_length=1, max_length=120)
    source_ref: str = ""


@router.get("/settings")
async def get_settings() -> dict:
    return public_settings()


@router.put("/settings")
async def put_settings(body: SettingsRequest) -> dict:
    try:
        return save_settings(
            app_id=body.app_id,
            app_secret=body.app_secret,
            account_name=body.account_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc


@router.post("/settings/test")
async def test_settings() -> dict:
    try:
        message = await test_connection()
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"message": f"微信连接失败：{str(exc)[:240]}"}) from exc
    return {"ok": True, "message": message}


@router.post("/parse")
async def parse(body: ParseRequest) -> dict:
    try:
        return await parse_source(body.feishu_url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)[:300]}) from exc


@router.post("/publish")
async def publish(body: PublishRequest) -> dict:
    try:
        return await create_draft(
            body.article,
            request_id=body.request_id,
            source_ref=body.source_ref,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"message": f"微信草稿创建失败：{str(exc)[:300]}"}) from exc


@router.get("/history")
async def history(limit: int = 10) -> dict:
    return {"records": recent_records(limit)}
