"""Feishu raw-block fetcher owned by the InTheLoop flow.

This copies the tiny fetch orchestration instead of importing the shared
document_pipeline, because that pipeline also brings in the main rule engine.
"""
from __future__ import annotations

import asyncio
from typing import Optional, Tuple

from .feishu.public_browser import fetch_public_feishu_raw_blocks
from .ir_models import WordParseResult


async def fetch_intheloop_feishu_raw_blocks(
    feishu_url: str,
    *,
    filename_hint: Optional[str] = None,
) -> Tuple[WordParseResult, str]:
    """Fetch a publicly shared Feishu document without an app identity."""
    del filename_hint
    return await asyncio.to_thread(fetch_public_feishu_raw_blocks, feishu_url)
