"""Feishu raw-block fetcher owned by the InTheLoop flow.

This copies the tiny fetch orchestration instead of importing the shared
document_pipeline, because that pipeline also brings in the main rule engine.
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional, Tuple

from .feishu.service import get_feishu_document_service
from .feishu.validate import validate_feishu_url
from .ir_models import WordParseResult


async def fetch_intheloop_feishu_raw_blocks(
    feishu_url: str,
    *,
    filename_hint: Optional[str] = None,
) -> Tuple[WordParseResult, str]:
    """Fetch Feishu blocks without invoking other product-tab rules.

    Public-browser mode is the default and needs no Feishu app. The old OpenAPI
    path remains available as an explicit rollback switch.
    """
    normalized = validate_feishu_url(feishu_url)
    mode = os.environ.get("FEISHU_FETCH_MODE", "public").strip().lower()
    if mode != "api":
        from .feishu.public_browser import fetch_public_feishu_raw_blocks

        return await asyncio.to_thread(fetch_public_feishu_raw_blocks, normalized)
    svc = get_feishu_document_service()
    return await svc.fetch_raw_blocks_from_url(
        normalized,
        filename_hint=filename_hint,
    )
