"""飞书 OpenAPI 直读解析：CloudDocRef -> RawBlock 列表。"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Set
import os

from ..ir_models import WordParseResult
from .client import FeishuApiClient
from .errors import FEISHU_API_ERROR, FEISHU_UNSUPPORTED_TYPE, FeishuServiceError
from .models import CloudDocRef
from .to_raw_blocks import feishu_blocks_to_raw_blocks

logger = logging.getLogger(__name__)

class FeishuDirectParser:
    """通过 Feishu blocks API 直读文档，并映射为 RawBlock。"""

    def __init__(self, client: FeishuApiClient) -> None:
        self._client = client
        self._page_size = self._resolve_page_size()

    def _resolve_page_size(self) -> int:
        raw = os.environ.get("FEISHU_BLOCKS_PAGE_SIZE", "500").strip()
        try:
            v = int(raw)
        except ValueError:
            v = 500
        return max(50, min(v, 500))

    async def parse_ref(
        self, ref: CloudDocRef, *, filename: str = ""
    ) -> WordParseResult:
        blocks = await self._fetch_document_blocks(ref)
        raw_blocks = feishu_blocks_to_raw_blocks(blocks)
        return WordParseResult(
            source="feishu",
            filename=filename,
            document_title=(ref.title or "").strip(),
            raw_block_list=raw_blocks,
            mammoth_messages=[],
        )

    async def _fetch_document_blocks(self, ref: CloudDocRef) -> List[Dict]:
        if ref.obj_type not in ("docx", "doc"):
            raise FeishuServiceError(
                f"暂不支持的飞书文档类型: {ref.obj_type}",
                FEISHU_UNSUPPORTED_TYPE,
            )

        api_prefix = "docx" if ref.obj_type == "docx" else "docs"
        # 先拿根 block 信息，作为 children 遍历起点。
        root = await self._client.request_json(
            "GET", f"/{api_prefix}/v1/documents/{ref.obj_token}"
        )
        root_data = root.get("data") or {}
        root_block_id = (
            root_data.get("document", {}).get("block_id")
            if isinstance(root_data.get("document"), dict)
            else None
        ) or root_data.get("block_id") or ref.obj_token
        if not isinstance(root_block_id, str) or not root_block_id.strip():
            raise FeishuServiceError("无法解析文档根 block_id", FEISHU_API_ERROR)

        logger.info(
            "开始直读飞书 blocks",
            extra={"obj_type": ref.obj_type, "source": ref.source, "token": ref.obj_token[:12]},
        )

        items = await self._fetch_all_descendant_blocks(
            api_prefix=api_prefix,
            document_token=ref.obj_token,
            root_block_id=root_block_id,
        )

        logger.info(
            "飞书 blocks 读取完成",
            extra={"obj_type": ref.obj_type, "item_count": len(items)},
        )
        return items

    async def _fetch_all_descendant_blocks(
        self, *, api_prefix: str, document_token: str, root_block_id: str
    ) -> List[Dict[str, Any]]:
        """
        从根节点递归拉取全部后代 block。
        仅拉一层会遗漏飞书文档中嵌套容器内的正文与元数据行（常见于 callout / quote / 列表容器）。
        """
        out: List[Dict[str, Any]] = []
        visited_parents: Set[str] = set()
        seen_block_ids: Set[str] = set()

        async def append_children(parent_id: str) -> None:
            if not parent_id or parent_id in visited_parents:
                return
            visited_parents.add(parent_id)

            children = await self._client.iter_document_child_blocks(
                api_prefix=api_prefix,
                document_token=document_token,
                parent_block_id=parent_id,
                page_size=self._page_size,
            )
            for block in children:
                if not isinstance(block, dict):
                    continue
                block_id = str(block.get("block_id") or "").strip()
                if block_id and block_id not in seen_block_ids:
                    seen_block_ids.add(block_id)
                    out.append(block)
                elif not block_id:
                    # 极少数异常返回没有 block_id，仍保留，避免数据无声丢失。
                    out.append(block)

                has_children = bool(
                    block.get("has_children")
                    or block.get("has_child")
                    or block.get("children")
                )
                if has_children and block_id and block_id not in visited_parents:
                    # 深度优先展开，使容器内的图片/段落紧跟容器出现，
                    # 避免广度优先把嵌套图位推到全文末尾。
                    await append_children(block_id)

        await append_children(root_block_id)
        return out
