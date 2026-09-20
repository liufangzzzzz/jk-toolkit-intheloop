"""官方 drive/v1/export_tasks：创建 → 轮询 → 下载 docx。"""
from __future__ import annotations

import asyncio
import logging
import os

from .client import FeishuApiClient
from .errors import FEISHU_EXPORT_FAILED, FEISHU_EXPORT_TIMEOUT, FeishuServiceError
from .models import CloudDocRef

logger = logging.getLogger(__name__)

# job_status: 0 成功；1 初始化；2 处理中（官方文档）
_JOB_SUCCESS = 0
_JOB_INIT = 1
_JOB_PROCESSING = 2


class ExportPipeline:
    def __init__(self, client: FeishuApiClient) -> None:
        self._client = client
        self._timeout_s = int(os.environ.get("FEISHU_EXPORT_TIMEOUT_S", "120"))
        self._poll_initial_s = float(os.environ.get("FEISHU_EXPORT_POLL_INITIAL_S", "1.0"))
        self._poll_max_s = float(os.environ.get("FEISHU_EXPORT_POLL_MAX_S", "5.0"))

    async def export_docx(self, ref: CloudDocRef) -> bytes:
        ticket = await self._create_export_task(ref)
        file_token = await self._poll_export_result(ref, ticket)
        return await self._client.download_bytes(
            f"/drive/v1/export_tasks/file/{file_token}/download"
        )

    async def _create_export_task(self, ref: CloudDocRef) -> str:
        data = await self._client.request_json(
            "POST",
            "/drive/v1/export_tasks",
            json_body={
                "file_extension": "docx",
                "token": ref.obj_token,
                "type": ref.obj_type,
            },
        )
        ticket = (data.get("data") or {}).get("ticket")
        if not ticket:
            raise FeishuServiceError("创建飞书导出任务失败：未返回 ticket", FEISHU_EXPORT_FAILED)
        logger.info(
            "飞书导出任务已创建",
            extra={
                "ticket": str(ticket)[:16],
                "obj_type": ref.obj_type,
                "source": ref.source,
            },
        )
        return str(ticket)

    async def _poll_export_result(self, ref: CloudDocRef, ticket: str) -> str:
        elapsed = 0.0
        interval = self._poll_initial_s

        while elapsed < self._timeout_s:
            data = await self._client.request_json(
                "GET",
                f"/drive/v1/export_tasks/{ticket}",
                params={"token": ref.obj_token},
            )
            result = (data.get("data") or {}).get("result") or {}
            status = result.get("job_status")
            if status == _JOB_SUCCESS:
                file_token = result.get("file_token")
                if not file_token:
                    raise FeishuServiceError(
                        "导出成功但未返回 file_token",
                        FEISHU_EXPORT_FAILED,
                    )
                return str(file_token)

            if status not in (_JOB_INIT, _JOB_PROCESSING, None):
                err_msg = result.get("job_error_msg") or f"job_status={status}"
                raise FeishuServiceError(
                    f"飞书导出失败：{err_msg}",
                    FEISHU_EXPORT_FAILED,
                )

            await asyncio.sleep(interval)
            elapsed += interval
            interval = min(interval * 1.5, self._poll_max_s)

        raise FeishuServiceError(
            f"飞书导出超时（>{self._timeout_s}s），请稍后重试或改用 Word 上传",
            FEISHU_EXPORT_TIMEOUT,
        )
