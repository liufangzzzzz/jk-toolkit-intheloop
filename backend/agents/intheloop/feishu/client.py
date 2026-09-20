"""飞书 Open API 低层 HTTP 客户端（token + 通用请求）。"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

from .errors import (
    FEISHU_API_ERROR,
    FEISHU_CONFIG_ERROR,
    FEISHU_DOC_NOT_FOUND,
    FEISHU_PERMISSION_DENIED,
    FEISHU_TOKEN_ERROR,
    FeishuServiceError,
)

logger = logging.getLogger(__name__)

_BASE = "https://open.feishu.cn/open-apis"
_TRANSIENT_ERROR_CODES = {
    99991663,  # 频率限制（常见）
    99991400,  # 服务繁忙（常见）
}


class FeishuApiClient:
    """tenant_access_token + JSON API；导出下载走 download_bytes。"""

    def __init__(self) -> None:
        self.app_id = os.environ.get("FEISHU_APP_ID", "")
        self.app_secret = os.environ.get("FEISHU_APP_SECRET", "")
        self._access_token: Optional[str] = None
        self._expire_at: int = 0

    async def get_access_token(self) -> str:
        now = int(time.time())
        if self._access_token and now < self._expire_at - 60:
            return self._access_token

        if not self.app_id or not self.app_secret:
            raise FeishuServiceError(
                "飞书配置未完成：请设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET",
                FEISHU_CONFIG_ERROR,
            )

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_BASE}/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            data = resp.json()

        if data.get("code") != 0:
            raise FeishuServiceError(
                f"飞书 Token 获取失败 [{data.get('code')}]: {data.get('msg', '')}",
                FEISHU_TOKEN_ERROR,
            )

        self._access_token = data["tenant_access_token"]
        self._expire_at = now + int(data.get("expire", 7200))
        logger.info("飞书 tenant_access_token 已刷新")
        return self._access_token

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        retry_on_401: bool = True,
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        retries = max(0, int(max_retries))
        for attempt in range(retries + 1):
            token = await self.get_access_token()
            headers = {"Authorization": f"Bearer {token}"}
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.request(
                        method,
                        f"{_BASE}{path}",
                        headers=headers,
                        params=params,
                        json=json_body,
                    )
            except httpx.RequestError as exc:
                if attempt < retries:
                    await self._backoff(attempt)
                    continue
                raise FeishuServiceError(
                    f"飞书 API 网络请求失败: {exc}",
                    FEISHU_API_ERROR,
                ) from exc

            if resp.status_code == 401 and retry_on_401:
                self._access_token = None
                retry_on_401 = False
                if attempt < retries:
                    continue
                return await self.request_json(
                    method, path, params=params, json_body=json_body, retry_on_401=False
                )

            if resp.status_code == 403:
                raise FeishuServiceError(
                    "飞书文档权限不足：请为文档「添加文档应用」；知识库页需应用具备知识库节点阅读权限",
                    FEISHU_PERMISSION_DENIED,
                )
            if resp.status_code == 404:
                raise FeishuServiceError("飞书资源不存在或已被删除", FEISHU_DOC_NOT_FOUND)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < retries:
                    await self._backoff(attempt)
                    continue
                raise FeishuServiceError("飞书 API 调用过于频繁或服务不可用", FEISHU_API_ERROR)

            try:
                data = resp.json()
            except Exception as exc:
                raise FeishuServiceError(
                    f"飞书 API 响应非 JSON（HTTP {resp.status_code}）",
                    FEISHU_API_ERROR,
                ) from exc

            if data.get("code") != 0:
                code = int(data.get("code", 0))
                msg = data.get("msg", "未知错误")
                if code in (131005, 1069906) or "not found" in msg.lower():
                    raise FeishuServiceError(f"飞书资源不存在 [{code}]: {msg}", FEISHU_DOC_NOT_FOUND)
                if code in (131006, 1069902, 110) or "permission" in msg.lower():
                    raise FeishuServiceError(
                        f"飞书权限不足 [{code}]: {msg}",
                        FEISHU_PERMISSION_DENIED,
                    )
                if code in _TRANSIENT_ERROR_CODES and attempt < retries:
                    await self._backoff(attempt)
                    continue
                raise FeishuServiceError(f"飞书 API 错误 [{code}]: {msg}", FEISHU_API_ERROR)
            return data
        raise FeishuServiceError("飞书 API 调用失败（重试耗尽）", FEISHU_API_ERROR)

    async def _backoff(self, attempt: int) -> None:
        await self._sleep(min(0.5 * (2**attempt), 3.0))

    async def _sleep(self, seconds: float) -> None:
        import asyncio

        await asyncio.sleep(seconds)

    async def download_bytes(self, path: str) -> bytes:
        token = await self.get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.get(f"{_BASE}{path}", headers=headers)
        except httpx.RequestError as exc:
            raise FeishuServiceError(
                f"飞书文件下载失败: {exc}",
                FEISHU_API_ERROR,
            ) from exc

        if resp.status_code != 200:
            raise FeishuServiceError(
                f"飞书文件下载失败（HTTP {resp.status_code}）",
                FEISHU_API_ERROR,
            )
        return resp.content

    async def get_wiki_node(self, node_token: str) -> Dict[str, Any]:
        data = await self.request_json(
            "GET",
            "/wiki/v2/spaces/get_node",
            params={"token": node_token},
        )
        node = (data.get("data") or {}).get("node") or {}
        if not node:
            raise FeishuServiceError("知识库节点信息为空", FEISHU_DOC_NOT_FOUND)
        return node

    async def batch_query_meta(self, doc_token: str, doc_type: str) -> Optional[Dict[str, Any]]:
        """drive/v1/metas/batch_query；失败返回 None。"""
        try:
            data = await self.request_json(
                "POST",
                "/drive/v1/metas/batch_query",
                json_body={
                    "request_docs": [{"doc_token": doc_token, "doc_type": doc_type}],
                },
            )
        except FeishuServiceError:
            return None
        metas = (data.get("data") or {}).get("metas") or []
        return metas[0] if metas else None

    async def iter_document_child_blocks(
        self, *, api_prefix: str, document_token: str, parent_block_id: str, page_size: int = 500
    ) -> List[Dict[str, Any]]:
        """
        拉取指定 parent 的全部子 block（自动分页）。
        api_prefix: docx | docs
        """
        items: List[Dict[str, Any]] = []
        page_token: Optional[str] = None
        while True:
            params: Dict[str, Any] = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            data = await self.request_json(
                "GET",
                f"/{api_prefix}/v1/documents/{document_token}/blocks/{parent_block_id}/children",
                params=params,
            )
            payload = data.get("data") or {}
            chunk = payload.get("items") or payload.get("children") or []
            if isinstance(chunk, dict):
                chunk = list(chunk.values())
            if isinstance(chunk, list):
                items.extend([x for x in chunk if isinstance(x, dict)])
            has_more = bool(payload.get("has_more"))
            page_token = payload.get("page_token") if has_more else None
            if not has_more:
                break
        return items

    async def update_block_text(
        self,
        *,
        document_token: str,
        block_id: str,
        text: str,
        api_prefix: str = "docx",
    ) -> Dict[str, Any]:
        """更新段落 block 的纯文本内容（仅摘要回写场景）。"""
        doc = (document_token or "").strip()
        bid = (block_id or "").strip()
        if not doc or not bid:
            raise FeishuServiceError("document_token 或 block_id 不能为空", FEISHU_API_ERROR)
        body = {
            "replace_image": False,
            "block": {
                "block_id": bid,
                "paragraph": {
                    "elements": [
                        {
                            "text_run": {
                                "content": str(text or ""),
                            }
                        }
                    ]
                },
            },
        }
        return await self.request_json(
            "PATCH",
            f"/{api_prefix}/v1/documents/{doc}/blocks/{bid}",
            json_body=body,
        )
