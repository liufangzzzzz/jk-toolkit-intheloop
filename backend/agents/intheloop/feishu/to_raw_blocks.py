"""飞书 OpenAPI Block 树 -> RawBlock 映射。"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple
import uuid

from ..ir_models import EmphasisSpan, RawBlock

logger = logging.getLogger(__name__)


def _new_id() -> str:
    return str(uuid.uuid4())


def _to_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return False


def _wrap_emphasis(text: str, *, bold: bool, italic: bool) -> str:
    if not text:
        return ""
    if bold and italic:
        return f"***{text}***"
    if bold:
        return f"**{text}**"
    if italic:
        return f"*{text}*"
    return text


def _extract_text_elements(
    elements: Iterable[Dict[str, Any]],
    *,
    inline_markdown: bool = True,
) -> Tuple[str, bool, bool, List[EmphasisSpan]]:
    chunks: List[str] = []
    has_bold = False
    has_italic = False
    spans: List[EmphasisSpan] = []
    for el in elements or []:
        if not isinstance(el, dict):
            continue
        text_run = el.get("text_run") or el.get("textRun") or {}
        mention = el.get("mention") or {}
        text = ""
        style: Dict[str, Any] = {}
        if isinstance(text_run, dict):
            text = str(text_run.get("content") or text_run.get("text") or "")
            style = text_run.get("text_element_style") or text_run.get("style") or {}
        elif isinstance(mention, dict):
            text = str(mention.get("title") or mention.get("text") or "")
            style = mention.get("text_element_style") or {}
        if isinstance(style, dict):
            is_bold = _to_bool(style.get("bold"))
            is_italic = _to_bool(style.get("italic"))
            has_bold = has_bold or is_bold
            has_italic = has_italic or is_italic
        else:
            is_bold = False
            is_italic = False
        if text:
            if inline_markdown:
                chunks.append(_wrap_emphasis(text, bold=is_bold, italic=is_italic))
            else:
                chunks.append(text)
            spans.append(EmphasisSpan(text=text, bold=is_bold, italic=is_italic))
    return "".join(chunks).strip(), has_bold, has_italic, spans


def _extract_text_and_style(
    block: Dict[str, Any],
    key: str,
    aliases: Optional[List[str]] = None,
    *,
    inline_markdown: bool = True,
) -> Tuple[str, bool, bool, List[EmphasisSpan]]:
    keys = [key]
    for a in aliases or []:
        if a and a not in keys:
            keys.append(a)
    for k in keys:
        payload = block.get(k) or {}
        if not isinstance(payload, dict):
            continue
        elements = payload.get("elements") or payload.get("text_elements") or []
        text, bold, italic, spans = _extract_text_elements(
            elements, inline_markdown=inline_markdown
        )
        if text:
            return text, bold, italic, spans
        # 即使文本为空，也要尽可能返回样式（避免极端块丢失加粗/斜体标志）
        if elements:
            return text, bold, italic, spans
    return "", False, False, []


def _extract_image_url(block: Dict[str, Any]) -> Optional[str]:
    image = block.get("image") or {}
    if not isinstance(image, dict):
        return None
    candidates = (
        image.get("origin_image_url"),
        image.get("origin_url"),
        image.get("url"),
        image.get("download_url"),
    )
    for c in candidates:
        if isinstance(c, str) and c.strip():
            return c.strip()
    token = image.get("token") or image.get("file_token")
    if isinstance(token, str) and token.strip():
        # 解析阶段只保留稳定引用，真实下载可在后续侧边服务完成。
        return f"feishu-image://{token.strip()}"
    return None


def _extract_file_payload(block: Dict[str, Any]) -> Dict[str, str]:
    file_payload = block.get("file") or {}
    if not isinstance(file_payload, dict):
        return {}
    name = str(file_payload.get("name") or "").strip()
    token = str(file_payload.get("token") or file_payload.get("file_token") or "").strip()
    return {"name": name, "token": token}


def _block_kind(block: Dict[str, Any]) -> str:
    # 文档 API 可能返回数字 block_type 或具名字段。
    bt = block.get("block_type")
    if isinstance(bt, str) and bt.strip():
        return bt.strip().lower()
    if "heading1" in block:
        return "heading1"
    if "heading2" in block:
        return "heading2"
    if "heading3" in block:
        return "heading3"
    if "paragraph" in block:
        return "paragraph"
    if "image" in block:
        return "image"
    if "file" in block:
        return "file"
    if "callout" in block:
        return "callout"
    if "quote" in block:
        return "quote"
    if "ordered" in block or "ordered_list" in block:
        return "ordered"
    if "bullet" in block or "bullet_list" in block:
        return "bullet"
    if "divider" in block:
        return "divider"
    if "table" in block:
        return "table"
    if isinstance(bt, int):
        # 飞书 docx API 常见枚举（不同版本存在差异，按文本块优先保守映射）。
        # 关键：2 为普通文本/段落，不应误映射为 heading1。
        mapping = {
            2: "paragraph",
            3: "heading1",
            4: "heading2",
            5: "heading3",
            6: "bullet",
            7: "ordered",
            9: "quote",
            12: "divider",
            13: "table",
            17: "callout",
            23: "file",
        }
        return mapping.get(bt, "paragraph")
    return "paragraph"


def _to_paragraph(
    *,
    text: str,
    bold: bool,
    italic: bool,
    original_tag: Optional[str],
    indent_level: int = 0,
    emphasis_spans: Optional[List[EmphasisSpan]] = None,
) -> RawBlock:
    return RawBlock(
        block_id=_new_id(),
        block_type="paragraph",
        text=text or "",
        bold=bold,
        italic=italic,
        align="left",
        indent_level=max(0, int(indent_level or 0)),
        is_empty=not bool((text or "").strip()),
        original_tag=original_tag,
        emphasis_spans=emphasis_spans or [],
    )


def _convert_single_block(block: Dict[str, Any]) -> List[RawBlock]:
    kind = _block_kind(block)
    if kind == "image":
        image_url = _extract_image_url(block)
        if not image_url:
            return []
        return [
            RawBlock(
                block_id=_new_id(),
                block_type="image",
                image_url=image_url,
                text="",
                bold=False,
                italic=False,
                align="left",
                indent_level=0,
                is_empty=False,
                original_tag="img",
            )
        ]

    if kind == "file":
        file_payload = _extract_file_payload(block)
        name = file_payload.get("name") or "未命名附件"
        return [
            RawBlock(
                block_id=str(block.get("block_id") or _new_id()),
                block_type="file",
                text=name,
                bold=False,
                italic=False,
                align="left",
                indent_level=0,
                is_empty=False,
                original_tag="file",
                extra=file_payload,
            )
        ]

    if kind == "divider":
        return [
            RawBlock(
                block_id=_new_id(),
                block_type="divider",
                text="",
                bold=False,
                italic=False,
                align="center",
                indent_level=0,
                is_empty=True,
                original_tag="hr",
            )
        ]

    if kind == "table":
        return [
            RawBlock(
                block_id=_new_id(),
                block_type="table",
                text="",
                bold=False,
                italic=False,
                align="left",
                indent_level=0,
                is_empty=True,
                original_tag="table",
            )
        ]

    # 标题映射（与 Word/层2 契约一致：h2→一级 heading1，h3→二级 heading2）
    # 飞书编辑器「标题2」= API heading2 → h2；「标题3」= API heading3 → h3
    # heading1（标题1）亦按一级处理
    if kind == "heading1":
        text, bold, italic, spans = _extract_text_and_style(
            block, "heading1", inline_markdown=False
        )
        return [_to_paragraph(text=text, bold=bold, italic=italic, original_tag="h2", emphasis_spans=spans)]
    if kind == "heading2":
        text, bold, italic, spans = _extract_text_and_style(
            block, "heading2", inline_markdown=False
        )
        return [_to_paragraph(text=text, bold=bold, italic=italic, original_tag="h2", emphasis_spans=spans)]
    if kind == "heading3":
        text, bold, italic, spans = _extract_text_and_style(
            block, "heading3", inline_markdown=False
        )
        return [_to_paragraph(text=text, bold=bold, italic=italic, original_tag="h3", emphasis_spans=spans)]

    if kind in ("bullet", "unordered", "bullet_list"):
        payload = block.get("bullet") or block.get("bullet_list") or {}
        elements = payload.get("elements") if isinstance(payload, dict) else []
        text, bold, italic, spans = _extract_text_elements(elements or [])
        return [
            _to_paragraph(
                text=text,
                bold=bold,
                italic=italic,
                original_tag="li_ul",
                indent_level=(payload.get("level") or 0) if isinstance(payload, dict) else 0,
                emphasis_spans=spans,
            )
        ]

    if kind in ("ordered", "ordered_list"):
        payload = block.get("ordered") or block.get("ordered_list") or {}
        elements = payload.get("elements") if isinstance(payload, dict) else []
        text, bold, italic, spans = _extract_text_elements(elements or [])
        return [
            _to_paragraph(
                text=text,
                bold=bold,
                italic=italic,
                original_tag="li_ol",
                indent_level=(payload.get("level") or 0) if isinstance(payload, dict) else 0,
                emphasis_spans=spans,
            )
        ]

    if kind in ("quote", "callout"):
        key = "quote" if kind == "quote" else "callout"
        text, bold, italic, spans = _extract_text_and_style(block, key)
        return [_to_paragraph(text=text, bold=bold, italic=italic, original_tag="p", emphasis_spans=spans)]

    # 默认 paragraph
    text, bold, italic, spans = _extract_text_and_style(
        block, "paragraph", aliases=["text"]
    )
    if not text and block.get("paragraph") is None:
        # 兼容少数块直接挂 elements
        text, bold, italic, spans = _extract_text_elements(block.get("elements") or [])
    return [_to_paragraph(text=text, bold=bold, italic=italic, original_tag="p", emphasis_spans=spans)]


def feishu_blocks_to_raw_blocks(blocks: List[Dict[str, Any]]) -> List[RawBlock]:
    out: List[RawBlock] = []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        out.extend(_convert_single_block(block))

    # 生成块链
    for i, b in enumerate(out):
        prev_id = out[i - 1].block_id if i > 0 else None
        next_id = out[i + 1].block_id if i + 1 < len(out) else None
        out[i] = b.model_copy(update={"prev_block_id": prev_id, "next_block_id": next_id})

    # [DIAGNOSE] 诊断：层1 飞书 emphasis_spans 统计
    para_blocks = [b for b in out if b.block_type == "paragraph"]
    with_spans = sum(1 for b in para_blocks if b.emphasis_spans)
    with_bold = sum(
        1 for b in para_blocks
        if any(s.bold or s.italic for s in b.emphasis_spans)
    )
    with_text_bold = sum(1 for b in para_blocks if "**" in b.text)
    logger.info(
        "[EMPHASIS-DIAG] 层1-飞书: total=%d para=%d with_spans=%d with_bold_span=%d with_**=%d",
        len(out), len(para_blocks), with_spans, with_bold, with_text_bold,
    )

    return out
