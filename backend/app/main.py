from __future__ import annotations

import asyncio
import mimetypes
import os

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agents.intheloop.feishu.image_resolver import fetch_feishu_image_bytes_from_token
from agents.intheloop.feishu.public_image_store import fetch_public_image
from agents.intheloop.renderer import template_image_url

from .auth import (
    auth_enabled,
    clear_session_cookie,
    create_session_cookie,
    is_authenticated,
    set_initial_password,
    setup_required,
    verify_password,
)
from .modules.wechat_draft.routes import router as wechat_draft_router
from .modules.website_ingest.routes import agent_router as website_agent_router
from .modules.website_ingest.routes import router as website_ingest_router

load_dotenv()

app = FastAPI(title="In The Loop 运营工作台", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        item.strip()
        for item in os.environ.get("ITL_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
        if item.strip()
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Agent-Key", "Idempotency-Key"],
)
app.include_router(wechat_draft_router)
app.include_router(website_ingest_router)
app.include_router(website_agent_router)


class LoginRequest(BaseModel):
    password: str
    scope: str = "intheloop"


class SetupRequest(BaseModel):
    password: str = Field(min_length=8)


@app.get("/health/live")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/v1/auth/me")
async def auth_me(request: Request) -> dict:
    authenticated = is_authenticated(request, "intheloop")
    return {
        "authenticated": authenticated,
        "auth_enabled": auth_enabled("intheloop"),
        "unlocked_scopes": ["intheloop"] if authenticated else [],
        "setup_required": setup_required("intheloop"),
    }


@app.post("/api/v1/auth/setup")
async def auth_setup(body: SetupRequest, response: Response) -> dict:
    try:
        set_initial_password(body.password)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc)}) from exc
    create_session_cookie(response, "intheloop")
    return {"authenticated": True, "auth_enabled": True, "setup_required": False}


@app.post("/api/v1/auth/login")
async def auth_login(body: LoginRequest, response: Response) -> dict:
    scope = body.scope.strip().lower() or "intheloop"
    if setup_required(scope):
        raise HTTPException(status_code=409, detail={"message": "请先设置管理密码"})
    if not verify_password(body.password, scope):
        raise HTTPException(status_code=401, detail={"message": "访问密码错误"})
    create_session_cookie(response, scope)
    return {"authenticated": True, "auth_enabled": True, "scope": scope}


@app.post("/api/v1/auth/logout")
async def auth_logout(response: Response) -> dict:
    clear_session_cookie(response, "intheloop")
    return {"authenticated": False, "auth_enabled": auth_enabled("intheloop")}


@app.get("/api/v1/intheloop/feishu-image")
async def feishu_image(request: Request, token: str = Query(min_length=1)) -> Response:
    if not is_authenticated(request, "intheloop"):
        raise HTTPException(status_code=401, detail={"message": "请先登录内容发布台"})
    result = await asyncio.to_thread(fetch_feishu_image_bytes_from_token, f"feishu-image://{token.strip()}")
    if not result:
        raise HTTPException(status_code=404, detail={"message": "飞书图片无法加载"})
    raw, filename = result
    return Response(content=raw, media_type=mimetypes.guess_type(filename)[0] or "image/jpeg")


@app.get("/api/v1/intheloop/public-image")
async def public_image(request: Request, token: str = Query(min_length=1)) -> Response:
    if not is_authenticated(request, "intheloop"):
        raise HTTPException(status_code=401, detail={"message": "请先登录内容发布台"})
    result = await asyncio.to_thread(fetch_public_image, token.strip())
    if not result:
        raise HTTPException(status_code=404, detail={"message": "公开文档图片已过期，请重新解析文档"})
    raw, _filename, mime = result
    return Response(content=raw, media_type=mime)


@app.get("/api/v1/intheloop/template-image")
async def template_image(request: Request, key: str = Query(min_length=1)) -> Response:
    if not is_authenticated(request, "intheloop"):
        raise HTTPException(status_code=401, detail={"message": "请先登录内容发布台"})
    url = template_image_url(key.strip())
    if not url:
        raise HTTPException(status_code=404, detail={"message": "模板图片不存在"})
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        response = await client.get(url)
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail={"message": "模板图片不可用"})
    return Response(content=response.content, media_type=response.headers.get("content-type", "image/png"))
