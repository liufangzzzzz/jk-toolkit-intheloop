from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode

from fastapi import HTTPException, Request, Response

from .settings_store import load_settings, update_settings

COOKIE_PREFIX = "toolkit_session"
SESSION_SECONDS = 7 * 24 * 60 * 60
_SCOPE_RE = re.compile(r"^[a-z0-9_]{1,40}$")


def _normalize_scope(scope: str) -> str:
    value = (scope or "intheloop").strip().lower().replace("-", "_")
    return value if _SCOPE_RE.fullmatch(value) else "intheloop"


def _password(scope: str = "intheloop") -> str:
    normalized = _normalize_scope(scope)
    scoped = os.environ.get(f"TOOLKIT_{normalized.upper()}_PASSWORD", "").strip()
    if scoped:
        return scoped
    if normalized == "intheloop":
        return os.environ.get("ITL_ACCESS_PASSWORD", "").strip()
    return ""


def setup_required(scope: str = "intheloop") -> bool:
    normalized = _normalize_scope(scope)
    if _password(normalized):
        return False
    if normalized != "intheloop":
        return True
    auth = load_settings().get("auth") or {}
    return not bool(auth.get("password_hash") and auth.get("password_salt"))


def set_initial_password(password: str) -> None:
    if not setup_required("intheloop"):
        raise ValueError("管理密码已经设置")
    if len(password) < 8:
        raise ValueError("管理密码至少需要 8 位")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    update_settings(
        "auth",
        password_salt=urlsafe_b64encode(salt).decode("ascii"),
        password_hash=urlsafe_b64encode(digest).decode("ascii"),
        session_secret=secrets.token_urlsafe(48),
    )


def _secret(scope: str = "intheloop") -> bytes:
    stored = str((load_settings().get("auth") or {}).get("session_secret") or "")
    raw = os.environ.get("ITL_SESSION_SECRET", "").strip() or stored or _password(scope)
    return raw.encode("utf-8")


def auth_enabled(scope: str = "intheloop") -> bool:
    return not setup_required(scope)


def _cookie_name(scope: str) -> str:
    return f"{COOKIE_PREFIX}_{_normalize_scope(scope)}"


def _signature(scope: str, expires_at: str) -> str:
    normalized = _normalize_scope(scope)
    payload = f"{normalized}.{expires_at}".encode("ascii")
    digest = hmac.new(_secret(normalized), payload, hashlib.sha256).digest()
    return urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def create_session_cookie(response: Response, scope: str = "intheloop") -> None:
    normalized = _normalize_scope(scope)
    expires_at = str(int(time.time()) + SESSION_SECONDS)
    value = f"{expires_at}.{_signature(normalized, expires_at)}"
    response.set_cookie(
        _cookie_name(normalized),
        value,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=os.environ.get("ITL_COOKIE_SECURE", "true").lower() not in {"0", "false", "no"},
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, scope: str = "intheloop") -> None:
    response.delete_cookie(_cookie_name(scope), path="/")


def verify_password(candidate: str, scope: str = "intheloop") -> bool:
    expected = _password(scope)
    if expected:
        return hmac.compare_digest(candidate or "", expected)
    if _normalize_scope(scope) != "intheloop":
        return False
    auth = load_settings().get("auth") or {}
    try:
        salt = urlsafe_b64decode(str(auth["password_salt"]).encode("ascii"))
        expected_hash = urlsafe_b64decode(str(auth["password_hash"]).encode("ascii"))
        candidate_hash = hashlib.scrypt((candidate or "").encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
        return hmac.compare_digest(candidate_hash, expected_hash)
    except (KeyError, TypeError, ValueError):
        return False


def is_authenticated(request: Request, scope: str = "intheloop") -> bool:
    normalized = _normalize_scope(scope)
    if setup_required(normalized):
        return False
    if not auth_enabled(normalized):
        return True
    raw = request.cookies.get(_cookie_name(normalized), "")
    try:
        expires_at, signature = raw.split(".", 1)
        return int(expires_at) > int(time.time()) and hmac.compare_digest(
            signature, _signature(normalized, expires_at)
        )
    except (TypeError, ValueError):
        return False


def require_auth(request: Request) -> None:
    if not is_authenticated(request, "intheloop"):
        raise HTTPException(status_code=401, detail={"message": "请先登录内容发布台"})
