"""Read public Feishu documents in a real browser, without an OpenAPI app."""
from __future__ import annotations

import base64
import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

from ..ir_models import RawBlock, WordParseResult
from .errors import (
    FEISHU_API_ERROR,
    FEISHU_LINK_INVALID,
    FEISHU_PERMISSION_DENIED,
    FEISHU_UNSUPPORTED_TYPE,
    FeishuServiceError,
)
from .public_image_store import store_public_image

logger = logging.getLogger(__name__)

_ALLOWED_HOST_SUFFIXES = (".feishu.cn", ".larksuite.com", ".larkoffice.com")
_IMAGE_RE = re.compile(r"^!\[(?P<alt>[^]]*)]\((?P<url>.+)\)$")
_LINK_ONLY_RE = re.compile(r"^\[(?P<label>[^]]+)]\((?P<url>[^)]+)\)$")
_HEADING_RE = re.compile(r"^(?P<marks>#{1,6})\s+(?P<text>.+)$")
_LIST_RE = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)(?P<text>.+)$")
_MD_LINK_RE = re.compile(r"\[([^]]+)]\([^)]+\)")
_MD_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>])")


def validate_public_feishu_url(url: str) -> str:
    normalized = (url or "").strip()
    if not normalized.startswith(("https://", "http://")):
        normalized = "https://" + normalized
    parsed = urlparse(normalized)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    allowed = any(hostname == suffix[1:] or hostname.endswith(suffix) for suffix in _ALLOWED_HOST_SUFFIXES)
    if parsed.scheme != "https" or not allowed or parsed.port not in (None, 443):
        raise FeishuServiceError(
            "请提交以 https:// 开头的飞书文档公开链接",
            FEISHU_LINK_INVALID,
        )
    if not re.match(r"^/(?:docx|wiki)/", parsed.path or "", re.I):
        raise FeishuServiceError(
            "无应用模式目前支持飞书新版文档 /docx/ 和知识库 /wiki/ 链接",
            FEISHU_UNSUPPORTED_TYPE,
        )
    return normalized


def _timeout_ms() -> int:
    try:
        return max(10_000, min(int(os.environ.get("FEISHU_PUBLIC_TIMEOUT_MS", "60000")), 120_000))
    except ValueError:
        return 60_000


def _clean_markdown_text(value: str) -> str:
    value = _MD_LINK_RE.sub(r"\1", value or "")
    value = _MD_ESCAPE_RE.sub(r"\1", value)
    return value.strip()


def _markdown_to_word_result(markdown: str, title: str) -> WordParseResult:
    blocks: list[RawBlock] = []
    paragraph_lines: list[str] = []
    in_fence = False
    in_table = False
    fence_lines: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        text = _clean_markdown_text("\n".join(paragraph_lines))
        paragraph_lines.clear()
        if text:
            blocks.append(RawBlock(block_type="paragraph", text=text, original_tag="p"))

    lines = (markdown or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for index, raw in enumerate(lines):
        line = raw.strip()
        if index == 0 and line.startswith("# "):
            continue
        if line.startswith("```"):
            if in_fence:
                text = "\n".join(fence_lines).strip()
                if text:
                    blocks.append(RawBlock(block_type="paragraph", text=text, original_tag="pre"))
                fence_lines.clear()
                in_fence = False
            else:
                flush_paragraph()
                in_fence = True
            continue
        if in_fence:
            fence_lines.append(raw)
            continue
        if not line:
            flush_paragraph()
            in_table = False
            continue
        if line.startswith("<iframe"):
            flush_paragraph()
            continue

        image_match = _IMAGE_RE.match(line)
        if image_match:
            flush_paragraph()
            image_url = image_match.group("url").strip().strip("<>")
            # Only cached public images are accepted. Browser asset placeholders
            # represent unsupported/failed assets and must not leak downstream.
            if image_url.startswith("public-image://"):
                blocks.append(
                    RawBlock(
                        block_id=image_url.removeprefix("public-image://")[:16],
                        block_type="image",
                        image_url=image_url,
                    )
                )
                alt = _clean_markdown_text(image_match.group("alt"))
                if alt:
                    blocks.append(RawBlock(block_type="paragraph", text=f"图注：{alt}", original_tag="p"))
            continue

        heading_match = _HEADING_RE.match(line)
        if heading_match:
            flush_paragraph()
            level = len(heading_match.group("marks"))
            blocks.append(
                RawBlock(
                    block_type="paragraph",
                    text=_clean_markdown_text(heading_match.group("text")),
                    original_tag=f"h{level}",
                )
            )
            continue
        if line.startswith("|") and line.endswith("|"):
            flush_paragraph()
            if not in_table:
                blocks.append(RawBlock(block_type="table", text=line, original_tag="table"))
                in_table = True
            continue
        in_table = False
        list_match = _LIST_RE.match(line)
        if list_match:
            flush_paragraph()
            blocks.append(
                RawBlock(
                    block_type="paragraph",
                    text=_clean_markdown_text(list_match.group("text")),
                    original_tag="li_ul",
                )
            )
            continue
        if line.startswith(">"):
            flush_paragraph()
            blocks.append(
                RawBlock(
                    block_type="paragraph",
                    text=_clean_markdown_text(line.lstrip("> ")),
                    original_tag="blockquote",
                )
            )
            continue
        if _LINK_ONLY_RE.match(line):
            # File attachments (including videos) are intentionally ignored.
            flush_paragraph()
            continue
        paragraph_lines.append(raw.strip())

    flush_paragraph()
    if in_fence and fence_lines:
        blocks.append(RawBlock(block_type="paragraph", text="\n".join(fence_lines).strip(), original_tag="pre"))
    return WordParseResult(
        source="feishu-public-browser",
        filename="feishu-public.docx",
        document_title=_clean_markdown_text(title),
        raw_block_list=blocks,
        mammoth_messages=[],
    )


def fetch_public_feishu_raw_blocks(url: str) -> tuple[WordParseResult, str]:
    """Synchronously open a public page and return only text and image blocks."""
    normalized = validate_public_feishu_url(url)
    try:
        from feishu_docx.core.browser_export import BrowserMarkdownExporter
        from feishu_docx.core.browser_export import BrowserDocumentModel, BrowserFallbackError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise FeishuServiceError(
            "服务器未安装飞书公开文档浏览器依赖",
            FEISHU_API_ERROR,
        ) from exc

    timeout_ms = _timeout_ms()
    exporter = BrowserMarkdownExporter(
        headless=True,
        timeout_ms=timeout_ms,
        scroll_rounds=80,
        scroll_wait_ms=200,
        executable_path=os.environ.get("FEISHU_PUBLIC_CHROMIUM_PATH") or None,
    )

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=exporter.executable_path,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(ignore_https_errors=False)
            page = context.new_page()
            try:
                page.goto(normalized, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    model = exporter.document_extractor.extract_from_page(page)
                except BrowserFallbackError as extraction_exc:
                    # Whiteboards, synced blocks and embedded apps can remain in
                    # a perpetual pending state. They are intentionally outside
                    # this product's scope, so keep the already-loaded article
                    # text/images instead of rejecting the whole document.
                    if "未加载完成" not in str(extraction_exc):
                        raise
                    payload = page.evaluate(exporter.document_extractor.SERIALIZE_BLOCK_TREE_JS)
                    if not payload or not payload.get("root"):
                        raise
                    model = BrowserDocumentModel(
                        title=str(payload.get("title") or page.title() or "untitled")
                        .replace("\r", " ")
                        .replace("\n", " ")
                        .strip(),
                        root=payload["root"],
                    )
                    logger.info("飞书复杂组件未完成加载，继续提取正文与普通图片")
                markdown = exporter.markdown_parser.parse_document(model)
                assets: list[dict[str, Any]] = exporter.asset_downloader._collect_assets(model.root)
                downloaded = 0
                for asset in assets:
                    if asset.get("asset_type") != "image":
                        continue
                    try:
                        payload = page.evaluate(exporter.asset_downloader.DOWNLOAD_ASSET_JS, asset)
                        if not payload or not payload.get("base64"):
                            continue
                        data = base64.b64decode(str(payload["base64"]), validate=False)
                        image_ref = store_public_image(data)
                        markdown = markdown.replace(str(asset["placeholder"]), image_ref)
                        downloaded += 1
                    except Exception as image_exc:
                        logger.warning("公开飞书图片下载失败: %s", image_exc)
                logger.info("公开飞书文档解析完成 title=%s images=%s", model.title, downloaded)
                result = _markdown_to_word_result(markdown, model.title)
                if not result.raw_block_list:
                    raise FeishuServiceError("公开文档没有可读正文", FEISHU_API_ERROR)
                return result, result.filename
            finally:
                context.close()
                browser.close()
    except FeishuServiceError:
        raise
    except PlaywrightTimeoutError as exc:
        raise FeishuServiceError(
            "无法读取该飞书文档，请确认已开启「互联网用户可阅读」",
            FEISHU_PERMISSION_DENIED,
        ) from exc
    except Exception as exc:
        message = str(exc).strip()[:240]
        raise FeishuServiceError(
            f"飞书公开文档解析失败：{message or '未知错误'}",
            FEISHU_API_ERROR,
        ) from exc
