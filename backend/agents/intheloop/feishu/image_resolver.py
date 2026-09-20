"""飞书图片 token -> 可上传图片字节。"""
from __future__ import annotations

import mimetypes
import os
import time
from typing import Optional, Tuple

import httpx

_BASE = "https://open.feishu.cn/open-apis"
_TOKEN_PREFIX = "feishu-image://"

_tenant_access_token: str = ""
_tenant_expire_at: int = 0


def _content_type_to_ext(content_type: str) -> str:
    ctype = (content_type or "").split(";")[0].strip().lower()
    guessed = mimetypes.guess_extension(ctype) if ctype else None
    ext = (guessed or ".jpg").lstrip(".")
    if ext == "jpeg":
        ext = "jpg"
    return ext or "jpg"


def _ensure_tenant_access_token(timeout_s: float = 15.0) -> Optional[str]:
    global _tenant_access_token, _tenant_expire_at
    now = int(time.time())
    if _tenant_access_token and now < _tenant_expire_at - 60:
        return _tenant_access_token

    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        return None

    with httpx.Client(timeout=timeout_s) as client:
        resp = client.post(
            f"{_BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
    if int(data.get("code", -1)) != 0:
        return None
    token = str(data.get("tenant_access_token") or "").strip()
    if not token:
        return None
    _tenant_access_token = token
    _tenant_expire_at = now + int(data.get("expire", 7200) or 7200)
    return _tenant_access_token


def fetch_feishu_image_bytes_from_token(
    token_uri: str, timeout_s: float = 20.0
) -> Optional[Tuple[bytes, str]]:
    """
    将 feishu-image://<file_token> 解析为 (bytes, filename)。
    """
    src = (token_uri or "").strip()
    if not src.startswith(_TOKEN_PREFIX):
        return None
    file_token = src[len(_TOKEN_PREFIX) :].strip()
    if not file_token:
        return None

    tenant_token = _ensure_tenant_access_token(timeout_s=min(timeout_s, 15.0))
    if not tenant_token:
        return None

    headers = {"Authorization": f"Bearer {tenant_token}"}
    url = f"{_BASE}/drive/v1/medias/{file_token}/download"
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
        if resp.status_code != 200 or not resp.content:
            return None
        ext = _content_type_to_ext(resp.headers.get("content-type") or "")
        return resp.content, f"image.{ext}"
    except Exception:
        return None

