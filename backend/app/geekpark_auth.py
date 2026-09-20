from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

import httpx

AuthorId: TypeAlias = int | str


def normalize_author_id(raw: object) -> AuthorId:
    """Keep UUID author IDs as strings while preserving legacy numeric IDs."""
    if raw is None or isinstance(raw, bool):
        raise ValueError("无法取得官网作者信息")
    if isinstance(raw, int):
        return raw
    value = str(raw).strip()
    if not value:
        raise ValueError("无法取得官网作者信息")
    return int(value) if value.isdigit() else value


@dataclass(frozen=True)
class GeekparkLoginResult:
    access_key: str
    nickname: str
    author_id: AuthorId


async def login_geekpark(login_name: str, password: str) -> GeekparkLoginResult:
    account_base = "https://account.geekpark.net"
    api_base = "https://mainssl.geekpark.net"
    name = login_name.strip()
    if not name or not password:
        raise ValueError("请输入极客公园账号和密码")

    headers = {"content-type": "application/json; charset=utf-8"}
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        try:
            await client.request("DELETE", f"{account_base}/logout", headers=headers)
        except Exception:
            pass
        response = await client.post(
            f"{account_base}/login",
            json={"login_name": name, "password": password},
            headers=headers,
        )
        if response.status_code >= 400:
            raise ValueError("极客公园账号或密码错误")

        response = await client.get(f"{account_base}/my/access_key", headers=headers)
        if response.status_code >= 300:
            raise ValueError("无法取得官网发布权限")
        access_key = str(response.json().get("access_key") or "").strip()
        if not access_key:
            raise ValueError("无法取得官网发布权限")

        response = await client.get(
            f"{api_base}/api/v1/admin/info",
            params={"access_key": access_key, "roles": "dev"},
            headers=headers,
        )
        if response.status_code >= 400:
            raise ValueError("当前账号没有官网后台权限")
        info = response.json()
        roles = info.get("roles") or []
        roles = [roles] if isinstance(roles, str) else [str(item) for item in roles]
        if "public" not in roles or "admin" not in roles:
            raise ValueError("当前账号没有官网发稿权限")
        nickname = str(info.get("nickname") or name).strip()

        response = await client.get(
            f"{account_base}/admin/users",
            params={"mode": "filter", "role": "admin", "nickname": nickname},
            headers=headers,
        )
        rows = response.json().get("json") or [] if response.status_code < 400 else []
        if not rows or rows[0].get("id") is None:
            raise ValueError("无法取得官网作者信息")
        author_id = normalize_author_id(rows[0]["id"])

    return GeekparkLoginResult(access_key=access_key, nickname=nickname, author_id=author_id)


async def list_geekpark_columns() -> list[dict]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get("https://mainssl.geekpark.net/api/v1/admin/columns", params={"per": 10000})
    response.raise_for_status()
    columns = response.json().get("columns") or []
    return [
        {"id": int(item["id"]), "title": str(item.get("title") or "")}
        for item in columns
        if item.get("id") is not None and item.get("title") not in {"科技快讯", "业界快讯"}
    ]
