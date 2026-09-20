"""Deterministic Feishu parser for the InTheLoop product flow.

No LLM, no fuzzy guessing: unmatched text stays an ordinary paragraph.
"""
from __future__ import annotations

import re
from typing import List, Optional

from .ir_models import RawBlock, WordParseResult
from .schema import InTheLoopArticle, InTheLoopBlock
from .text_normalize import normalize_line_for_intheloop_rule_match

_AUTHOR_RE = re.compile(
    r"^(?:\*{1,3}\s*)?作者(?:\s*\*{1,3}\s*)*[|｜:：]\s*(.+)$",
    re.I,
)
_EDITOR_RE = re.compile(
    r"^(?:\*{1,3}\s*)?编辑(?:\s*\*{1,3}\s*)*[|｜:：]\s*(.+)$",
    re.I,
)
_AUTHOR_LABEL_ONLY_RE = re.compile(
    r"^(?:\*{1,3}\s*)?作者(?:\s*\*{1,3}\s*)*[|｜:：]\s*$",
    re.I,
)
_EDITOR_LABEL_ONLY_RE = re.compile(
    r"^(?:\*{1,3}\s*)?编辑(?:\s*\*{1,3}\s*)*[|｜:：]\s*$",
    re.I,
)
_WHY_LABEL_RE = re.compile(r"^why\s+it\s+matters\s*$", re.I)
_WHY_LABEL_INLINE_RE = re.compile(r"^why\s+it\s+matters\s*[：:]\s*(.+)$", re.I)
_HEADER_SOURCE_RE = re.compile(r"^\*?\s*头图来源\s*[：:]\s*(.+)$")
_CAPTION_RE = re.compile(r"^(?:[#＃]{1,6}\s*)?图注\s*[：:]\s*(.+)$")
_QUESTION_RE = re.compile(r"^问\s*[：:]\s*(.+)$")
_ANSWER_RE = re.compile(r"^(.{1,24}?)\s*[：:]\s*(.+)$")
_NUMBERED_HEADING_RE = re.compile(
    r"^(?:(?:0[1-9][0-9]?)(?=\s+)|(?:\d{1,2})(?=[.．、:：_-]))"
    r"\s*[.．、:：_-]?\s*(.+)$"
)
_LEADING_NUMBER_RE = re.compile(
    r"^(?:(?:0[1-9][0-9]?)(?=\s+)|(?:\d{1,2})(?=[.．、:：_-]))"
    r"\s*[.．、:：_-]?\s*"
)
_LIST_TAGS = {"li_ul", "li_ol", "ul", "ol"}


def _plain(text: str) -> str:
    return normalize_line_for_intheloop_rule_match(str(text or ""))


def _strip_number_prefix(text: str) -> str:
    return _LEADING_NUMBER_RE.sub("", text, count=1).strip()


def _heading_title(text: str, original_tag: Optional[str]) -> Optional[str]:
    tag = str(original_tag or "").lower()
    if tag in _LIST_TAGS:
        return None
    normalized = _plain(text)
    if not normalized:
        return None
    if tag in ("h2", "h3", "heading1", "heading2", "heading3"):
        return _strip_number_prefix(normalized) or None
    m = _NUMBERED_HEADING_RE.match(normalized)
    if m:
        title = (m.group(1) or "").strip()
        return title or None
    return None


def _plain_capture(raw: str) -> str:
    return _plain(raw).strip()


class _ParserState:
    def __init__(self) -> None:
        self.article = InTheLoopArticle()
        self.pending_digest = False
        self.expect_answer = False
        self.pending_author = False
        self.pending_editor = False

    def _structural_line(self, normalized: str, original_tag: Optional[str]) -> bool:
        return bool(
            _HEADER_SOURCE_RE.match(normalized)
            or _AUTHOR_LABEL_ONLY_RE.match(normalized)
            or _EDITOR_LABEL_ONLY_RE.match(normalized)
            or _QUESTION_RE.match(normalized)
            or _CAPTION_RE.match(normalized)
            or _NUMBERED_HEADING_RE.match(normalized)
            or str(original_tag or "").lower() in ("h2", "h3")
            or _WHY_LABEL_RE.match(normalized)
            or _WHY_LABEL_INLINE_RE.match(normalized)
        )

    def process_line(self, raw_line: str, original_tag: Optional[str]) -> None:
        normalized = _plain(raw_line)
        if not normalized:
            return

        m = _HEADER_SOURCE_RE.match(normalized)
        if m:
            value = _plain_capture(m.group(1))
            if value:
                self.article.header_source = value
                self.expect_answer = False
            return

        m = _AUTHOR_RE.match(normalized)
        if m:
            value = _plain_capture(m.group(1))
            if value:
                self.article.author = value
                self.expect_answer = False
                self.pending_author = False
                self.pending_editor = False
            return

        m = _EDITOR_RE.match(normalized)
        if m:
            value = _plain_capture(m.group(1))
            if value:
                self.article.editor = value
                self.expect_answer = False
                self.pending_author = False
                self.pending_editor = False
            return

        if self.pending_author:
            if self._structural_line(normalized, original_tag):
                self.pending_author = False
            else:
                self.article.author = normalized
                self.pending_author = False
                return

        if self.pending_editor:
            if self._structural_line(normalized, original_tag):
                self.pending_editor = False
            else:
                self.article.editor = normalized
                self.pending_editor = False
                return

        if _AUTHOR_LABEL_ONLY_RE.match(normalized):
            self.pending_author = True
            return

        if _EDITOR_LABEL_ONLY_RE.match(normalized):
            self.pending_editor = True
            return

        m = _WHY_LABEL_INLINE_RE.match(normalized)
        if m:
            self.pending_digest = False
            value = _plain_capture(m.group(1))
            if value:
                self.article.digest = value
            return

        if _WHY_LABEL_RE.match(normalized):
            self.pending_digest = True
            self.expect_answer = False
            return

        if self.pending_digest:
            if self._structural_line(normalized, original_tag):
                self.pending_digest = False
            else:
                self.article.digest = normalized
                self.pending_digest = False
                return

        m = _QUESTION_RE.match(normalized)
        if m:
            content = _plain_capture(m.group(1))
            if content:
                self.article.blocks.append(
                    InTheLoopBlock(type="question", content=content)
                )
                self.expect_answer = True
            return

        if self.expect_answer:
            m = _ANSWER_RE.match(normalized)
            if m:
                speaker = _plain_capture(m.group(1))
                content = _plain_capture(m.group(2))
                self.article.blocks.append(
                    InTheLoopBlock(type="answer", speaker=speaker, content=content)
                )
                self.expect_answer = False
                return
            self.expect_answer = False

        m = _CAPTION_RE.match(normalized)
        if m:
            caption = _plain_capture(m.group(1))
            if caption:
                self.article.blocks.append(
                    InTheLoopBlock(type="caption", content=caption)
                )
            return

        title = _heading_title(normalized, original_tag)
        if title:
            self.article.blocks.append(
                InTheLoopBlock(type="heading", content=title)
            )
            return

        self.article.blocks.append(
            InTheLoopBlock(type="paragraph", content=normalized)
        )


def _process_raw_blocks(
    raw_blocks: List[RawBlock], article: InTheLoopArticle
) -> None:
    state = _ParserState()
    state.article = article
    video_count = 0
    attachment_count = 0

    for block in raw_blocks:
        if block.block_type == "image":
            state.pending_digest = False
            state.expect_answer = False
            if block.image_url:
                article.blocks.append(
                    InTheLoopBlock(
                        type="image",
                        url=block.image_url,
                        source_block_id=block.block_id,
                    )
                )
            continue

        if block.block_type == "table":
            article.warnings.append("表格块暂不支持，已跳过并提示人工检查")
            continue

        if block.block_type == "file":
            name = (block.text or "").strip() or "未命名附件"
            lower = name.lower()
            is_video = lower.endswith((".mp4", ".mov", ".m4v", ".avi", ".webm"))
            label = "视频附件" if is_video else "附件"
            if is_video:
                video_count += 1
            else:
                attachment_count += 1
            article.blocks.append(
                InTheLoopBlock(
                    type="file",
                    content=f"{label}：{name}",
                    source_block_id=block.block_id,
                )
            )
            continue

        if block.block_type == "divider":
            continue

        if block.block_type != "paragraph":
            article.warnings.append(
                f"未识别飞书块类型 {block.block_type!r}，已跳过"
            )
            continue

        for raw_line in re.split(r"[\r\n]+", block.text or ""):
            state.process_line(raw_line, block.original_tag)

    article.video_count = video_count
    article.attachment_count = attachment_count
    if video_count:
        article.warnings.append(
            f"检测到 {video_count} 个视频附件，当前不会自动嵌入公众号正文"
        )
    if attachment_count:
        article.warnings.append(
            f"检测到 {attachment_count} 个普通附件，当前不会自动嵌入正文"
        )


async def parse_feishu_document(
    feishu_url: str,
    *,
    filename_hint: Optional[str] = None,
) -> InTheLoopArticle:
    """Fetch a Feishu document through the configured public/API path."""
    from .feishu_fetcher import fetch_intheloop_feishu_raw_blocks

    parsed, _fname = await fetch_intheloop_feishu_raw_blocks(
        feishu_url,
        filename_hint=filename_hint,
    )
    return parse_word_result(parsed)


def parse_word_result(parsed: WordParseResult) -> InTheLoopArticle:
    """Convert an existing Feishu WordParseResult into an InTheLoopArticle."""
    title = _plain(parsed.document_title)
    article = InTheLoopArticle(title=title)
    _process_raw_blocks(parsed.raw_block_list, article)
    if parsed.source == "feishu-public-browser":
        article.warnings.append("已通过公开链接读取；视频和普通附件不会导入")
    if not article.title:
        article.warnings.append("未识别文档标题，请确认飞书文档标题")
    return article
