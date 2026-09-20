"""飞书文档统一解析管道（层1 + 层2）。"""
from __future__ import annotations

from typing import NoReturn, Optional, Tuple

from ..ir_models import WordParseResult
from .service import get_feishu_document_service
from .validate import validate_feishu_url


async def fetch_feishu_raw_blocks(
    feishu_url: str,
    *,
    filename_hint: Optional[str] = None,
) -> Tuple[WordParseResult, str]:
    """统一入口：飞书链接 -> WordParseResult(raw_block_list) + 文件名。"""
    normalized = validate_feishu_url(feishu_url)
    svc = get_feishu_document_service()
    return await svc.fetch_raw_blocks_from_url(
        normalized,
        filename_hint=filename_hint,
    )


def parse_feishu_to_marked_tree(*args: object, **kwargs: object) -> NoReturn:
    """Not part of the isolated InTheLoop flow."""
    del args, kwargs
    raise NotImplementedError("InTheLoop does not expose the shared rule-engine parser")

