"""飞书文档接入门面：链接 -> OpenAPI 直读 -> RawBlock。"""
from __future__ import annotations

import logging
from typing import Optional

from .client import FeishuApiClient
from .direct_parser import FeishuDirectParser
from .link_resolver import resolve_cloud_doc_ref, suggested_filename
from ..ir_models import WordParseResult

logger = logging.getLogger(__name__)

_facade: Optional["FeishuDocumentService"] = None


class FeishuDocumentService:
    """
    对外唯一入口（与 routes 对齐）。
    流程：解析链接 ->（wiki get_node）-> OpenAPI blocks 直读 -> RawBlock。
    """

    def __init__(self) -> None:
        self._client = FeishuApiClient()
        self._direct_parser = FeishuDirectParser(self._client)

    async def fetch_raw_blocks_from_url(
        self, feishu_url: str, *, filename_hint: Optional[str] = None
    ) -> tuple[WordParseResult, str]:
        """
        :return: (WordParseResult(source=feishu), suggested_filename)
        """
        ref = await resolve_cloud_doc_ref(feishu_url, self._client)
        logger.info(
            "飞书链接已解析",
            extra={
                "source": ref.source,
                "obj_type": ref.obj_type,
                "node_token": (ref.node_token or "")[:8] or None,
            },
        )
        fname = suggested_filename(ref, filename_hint)
        parsed = await self._direct_parser.parse_ref(ref, filename=fname)
        if not parsed.raw_block_list:
            from .errors import FEISHU_API_ERROR, FeishuServiceError

            raise FeishuServiceError("飞书直读解析结果为空", FEISHU_API_ERROR)
        return parsed, fname


def get_feishu_document_service() -> FeishuDocumentService:
    """进程内单例，复用 tenant_access_token 缓存。"""
    global _facade
    if _facade is None:
        _facade = FeishuDocumentService()
    return _facade
