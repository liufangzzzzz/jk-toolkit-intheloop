"""Source-maintained fixed InTheLoop renderer.

The approved InTheLoop HTML/CSS is kept in this module as constants.
It intentionally does not read user-editable template config.
"""
from __future__ import annotations

import html
import re
from typing import Dict, List, Optional
from urllib.parse import quote

from .schema import InTheLoopArticle, InTheLoopBlock

_FONT_STACK = (
    "Optima-Regular,PingFangTC-light,'PingFang SC','PingFang TC',"
    "'Hiragino Sans GB','Microsoft YaHei',sans-serif"
)
_AUTHOR_EDITOR_COLOR = "#A583FF"
_AUTHOR_PREFIX = "作者｜"
_EDITOR_PREFIX = "编辑｜"
_BODY_FONT_CSS = f"font-family:{_FONT_STACK};"
_PARAGRAPH_CSS = (
    f"{_BODY_FONT_CSS}font-size:16px;line-height:1.75;"
    "color:rgb(0,0,0);margin:0 8px 24px;text-align:justify;text-indent:0;"
)
_QUESTION_CSS = (
    f"{_BODY_FONT_CSS}color:rgb(165, 131, 255);font-size:16px;"
    "line-height:1.75;font-weight:bold;margin:0 8px 24px;"
    "text-align:justify;text-indent:0;"
)
_IMAGE_CSS = (
    "max-width:100%;height:auto;display:block;margin-left:auto;"
    "margin-right:auto;margin-top:24px;margin-bottom:24px;object-fit:contain;"
)
_CAPTION_CSS = (
    f"{_BODY_FONT_CSS}font-size:14px;line-height:1.6;margin:0 8px 24px;"
    "text-align:left;color:rgb(178, 178, 178);"
)
_OPENING_PLACEHOLDER_CSS = (
    f"{_BODY_FONT_CSS}font-size:15px;line-height:1.7;color:#9aa1ac;"
    "border:1px dashed #c7cbd3;border-radius:8px;padding:18px 16px;"
    "margin:0 8px 24px;text-align:left;"
)
_FOOTER_CSS = (
    f"{_BODY_FONT_CSS}font-size:14px;text-align:justify;"
    "color:rgb(136, 136, 136);margin:0 0 24px;line-height:1.6;"
)
_FOOTER_SECTION_CSS = (
    "font-family:Optima-Regular,PingFangTC-light,'PingFang SC',"
    "'PingFang TC','Hiragino Sans GB','Microsoft YaHei',sans-serif;"
    "margin-top:32px;padding:12px 8px 0;border-top:1px solid rgb(238, 238, 238);"
)

_DIGEST_SHELL_CSS = (
    "box-sizing:border-box;margin:0 8px 24px;padding:24px 20px;overflow:hidden;"
    "background:linear-gradient(100deg,rgb(111, 199, 255) 0%,"
    "rgb(173, 132, 253) 52%,rgb(243, 142, 239) 100%);color:rgb(255, 255, 255);"
    f"font-family:{_FONT_STACK};"
)
_DIGEST_TITLE_CSS = (
    "margin:0 0 18px;font-size:24px;font-weight:700;"
    "line-height:1.2;letter-spacing:0;color:rgb(255, 255, 255);"
)
_DIGEST_TEXT_CSS = (
    "margin:0;font-size:18px;font-weight:700;"
    "line-height:1.55;letter-spacing:0;text-align:left;color:rgb(255, 255, 255);"
)
_PLACEHOLDER_TEXT_CSS = (
    "margin:0;font-size:18px;font-weight:700;"
    "line-height:1.35;letter-spacing:0;text-align:left;color:rgb(255, 255, 255);"
)
_AUTHOR_EDITOR_CSS = (
    f"color:{_AUTHOR_EDITOR_COLOR};margin:0;line-height:1.5;"
    f"font-size:16px;font-weight:700;text-align:left;{_BODY_FONT_CSS}"
)
_HEADING_IMAGE_WIDTHS = ["50px", "50px", "50px"]
_HEADING_IMAGE_URLS = [
    "https://mmbiz.qpic.cn/mmbiz_png/ewz3sfllJmfdQeMz9ZnnMLqjbxglVhtnZTZmdjRZLicmbuiaPibBt9naJORe3OvAIeOt8PNMVpyFS5xEdkOtgoqKLTZ9fbz95WVIJmqX4D3uqY/640?wx_fmt=png&from=appmsg#imgIndex=4",
    "https://mmbiz.qpic.cn/sz_mmbiz_png/ewz3sfllJmdFD6iaGLvkG0Gfd2o9PrK3qiaMwp6AXsKypMPS1oRtTshCdV3aMDmJ9LAhXt254iaZGoFicTwndzFS5X9vgkFf8owFibBV3icbU2dCY/640?wx_fmt=png&from=appmsg",
    "https://mmbiz.qpic.cn/sz_mmbiz_png/ewz3sfllJmdd8IK2XAP29FvnwCWrSQA9OnGj1lu4pH71JJ1VpGkHheoVicHfSZaRtO2NDC0p0icJPD8urE7ahg6WsXiaJDfML82TticU9SfO3bw/640?wx_fmt=png&from=appmsg",
]
_FOOTER_IMAGE_URL = (
    "https://mmbiz.qpic.cn/sz_mmbiz_jpg/ewz3sfllJmf47sMoBPHF67s1LbtXX1wXviaE5QV5rmicP8vORjXHlWLncKoMxRcejPjjWurF9q6G59bCIuWOKBv62mHoAzCAWsz7UO0hYZkLY/640?wx_fmt=jpeg&from=appmsg"
)
_TEMPLATE_IMAGE_KEYS: Dict[str, str] = {
    "heading-1": _HEADING_IMAGE_URLS[0],
    "heading-2": _HEADING_IMAGE_URLS[1],
    "heading-3": _HEADING_IMAGE_URLS[2],
    "footer": _FOOTER_IMAGE_URL,
}
_ORIGINAL_DECLARATION = "本文为 In The Loop 原创文章，转载请联系作者"


def _style_attr(style: str) -> str:
    return f' style="{html.escape(style, quote=True)}"'


def _rich_text(raw: str) -> str:
    escaped = html.escape(str(raw or ""), quote=False)
    escaped = re.sub(
        r"\*\*\*(.+?)\*\*\*",
        r'<strong style="color:#A583FF;font-weight:700;"><em>\1</em></strong>',
        escaped,
        flags=re.S,
    )
    escaped = re.sub(
        r"\*\*(.+?)\*\*",
        r'<strong style="color:#A583FF;font-weight:700;">\1</strong>',
        escaped,
        flags=re.S,
    )
    return escaped


def _digest_html(article: InTheLoopArticle) -> str:
    if not article.digest.strip():
        return ""
    inner = _rich_text(article.digest.strip())
    return (
        f'<section{_style_attr(_DIGEST_SHELL_CSS)}>'
        f'<p{_style_attr(_DIGEST_TITLE_CSS)}>Why It Matters</p>'
        f'<p{_style_attr(_DIGEST_TEXT_CSS)}><span>{inner}</span></p>'
        "</section>"
    )


def _why_it_matters_placeholder_html() -> str:
    return (
        f'<section{_style_attr(_DIGEST_SHELL_CSS)}>'
        f'<p{_style_attr(_PLACEHOLDER_TEXT_CSS)}>Why It Matters / 待替换</p>'
        "</section>"
    )


def _why_it_matters_module_html(article: InTheLoopArticle) -> str:
    if article.digest.strip():
        return _digest_html(article)
    return _why_it_matters_placeholder_html()


def _author_editor_html(article: InTheLoopArticle) -> str:
    parts: List[str] = []
    if article.author.strip():
        author_margin_bottom = "8px" if article.editor.strip() else "24px"
        author_style = (
            f"{_AUTHOR_EDITOR_CSS}margin:0 8px {author_margin_bottom} 8px;"
        )
        parts.append(
            f'<p{_style_attr(author_style)}>'
            f"{_AUTHOR_PREFIX}{_rich_text(article.author.strip())}</p>"
        )
    if article.editor.strip():
        editor_style = (
            f"{_AUTHOR_EDITOR_CSS}margin:0 8px 24px 8px;"
        )
        parts.append(
            f'<p{_style_attr(editor_style)}>'
            f"{_EDITOR_PREFIX}{_rich_text(article.editor.strip())}</p>"
        )
    return "".join(parts)


def template_image_url(key: str) -> Optional[str]:
    return _TEMPLATE_IMAGE_KEYS.get(key)


def _template_image_src(key: str, *, preview: bool) -> str:
    url = _TEMPLATE_IMAGE_KEYS[key]
    if preview:
        return f"/api/v1/intheloop/template-image?key={quote(key)}"
    return url


def _heading_number_image(index: int, *, preview: bool = False) -> str:
    if index <= 0:
        return ""
    pos = index - 1
    if pos < len(_HEADING_IMAGE_URLS):
        url = _template_image_src(f"heading-{index}", preview=preview)
        width = _HEADING_IMAGE_WIDTHS[pos]
        return (
            f'<img src="{html.escape(url, quote=True)}"'
            f'{_style_attr(f"width:{width} !important;height:auto !important;"
                           "vertical-align:bottom;background-color:transparent;")}'
            ' alt="">'
        )
    return (
        f'<span style="font-size:36px;line-height:1;color:rgb(45,113,214);'
        f'font-weight:bold;">{index}.</span>'
    )


def _heading_html(block: InTheLoopBlock, index: int, *, preview: bool = False) -> str:
    title = _rich_text(block.content.strip())
    return (
        f'<section style="margin:16px 8px 24px;text-align:center;">'
        f"{_heading_number_image(index, preview=preview)}"
        "</section>"
        f'<section style="margin:0 8px 24px;text-align:center;">'
        f'<p style="font-family:{_FONT_STACK};font-size:18px;line-height:1.45;'
        f'font-weight:700;color:rgb(0,0,0);margin:0;">{title}</p>'
        "</section>"
    )


def _paragraph_html(block: InTheLoopBlock) -> str:
    return f'<p{_style_attr(_PARAGRAPH_CSS)}>{_rich_text(block.content)}</p>'


def _question_html(block: InTheLoopBlock) -> str:
    return (
        f'<p{_style_attr(_QUESTION_CSS)}>问：{_rich_text(block.content)}</p>'
    )


def _answer_html(block: InTheLoopBlock) -> str:
    if block.speaker.strip():
        body = (
            f'<strong style="color:rgb(165, 131, 255);font-weight:bold;">'
            f"{_rich_text(block.speaker.strip())}：</strong>"
            f'<span style="color:rgb(0,0,0);">{_rich_text(block.content)}</span>'
        )
    else:
        body = (
            f'<strong style="color:rgb(165, 131, 255);font-weight:bold;">答：</strong>'
            f'<span style="color:rgb(0,0,0);">{_rich_text(block.content)}</span>'
        )
    return f'<p{_style_attr(_PARAGRAPH_CSS)}>{body}</p>'


def _image_html(block: InTheLoopBlock) -> str:
    if not block.url:
        return ""
    return (
        f'<img src="{html.escape(block.url, quote=True)}"'
        f'{_style_attr(_IMAGE_CSS)} alt="">'
    )


def _caption_html(block: InTheLoopBlock) -> str:
    return f'<p{_style_attr(_CAPTION_CSS)}>{_rich_text(block.content)}</p>'


def _file_html(block: InTheLoopBlock) -> str:
    style = (
        f"{_BODY_FONT_CSS}font-size:14px;line-height:1.6;margin:0 8px 24px;"
        "padding:10px 12px;border:1px dashed rgb(210,210,210);"
        "color:rgb(102,102,102);background:rgb(250,250,250);"
    )
    return f'<p{_style_attr(style)}>{_rich_text(block.content)}</p>'


def _split_opening_blocks(
    article: InTheLoopArticle,
) -> tuple[List[InTheLoopBlock], List[InTheLoopBlock]]:
    """Split leading lead paragraphs from real section content.

    ARTICLE_OPENING ends before the first heading / question / answer. All
    leading plain paragraphs stay in the opening; every later heading starts
    SECTION_HEADING content.
    """
    boundary_types = {"heading", "question", "answer"}
    index = 0
    while index < len(article.blocks) and article.blocks[index].type not in boundary_types:
        index += 1
    return article.blocks[:index], article.blocks[index:]


def _render_opening_blocks(blocks: List[InTheLoopBlock]) -> str:
    if not any(block.type == "paragraph" for block in blocks):
        return (
            f'<section{_style_attr(_OPENING_PLACEHOLDER_CSS)}>'
            "此处为开场正文位置（未识别到内容，可后续补充）"
            "</section>"
        )
    parts: List[str] = []
    for block in blocks:
        if block.type == "paragraph":
            parts.append(_paragraph_html(block))
        elif block.type == "image":
            parts.append(_image_html(block))
        elif block.type == "caption":
            parts.append(_caption_html(block))
        elif block.type == "file":
            parts.append(_file_html(block))
    return "".join(parts)


def _body_html(blocks: List[InTheLoopBlock], *, preview: bool = False) -> str:
    """Render real SECTION_HEADING and later body blocks."""
    parts: List[str] = []
    heading_index = 0
    for block in blocks:
        if block.type == "heading":
            heading_index += 1
            parts.append(_heading_html(block, heading_index, preview=preview))
        elif block.type == "paragraph":
            parts.append(_paragraph_html(block))
        elif block.type == "question":
            parts.append(_question_html(block))
        elif block.type == "answer":
            parts.append(_answer_html(block))
        elif block.type == "image":
            parts.append(_image_html(block))
        elif block.type == "caption":
            parts.append(_caption_html(block))
        elif block.type == "file":
            parts.append(_file_html(block))
    return "".join(parts)


def _footer_html(article: InTheLoopArticle, *, preview: bool = False) -> str:
    lines: List[str] = []
    if article.header_source.strip():
        lines.append(
            f'<p{_style_attr(_FOOTER_CSS)}>'
            f"*头图来源：{_rich_text(article.header_source.strip())}</p>"
        )
    lines.append(
        f'<p{_style_attr(_FOOTER_CSS)}>{_ORIGINAL_DECLARATION}</p>'
    )
    image = (
        f'<img src="{html.escape(_template_image_src("footer", preview=preview), quote=True)}"'
        f'{_style_attr("display:block;width:100%;max-width:661px;height:auto;"
                       "margin:0 auto;vertical-align:bottom;")}'
        ' alt="">'
    )
    return f'<section{_style_attr(_FOOTER_SECTION_CSS)}>{"".join(lines)}{image}</section>'


def _article_opening_html(article: InTheLoopArticle) -> str:
    """Fixed ARTICLE_OPENING order: Why It Matters -> author metadata."""
    return (
        f"{_why_it_matters_module_html(article)}"
        f"{_author_editor_html(article)}"
    )


def _preview_src(raw_url: str) -> str:
    if raw_url.startswith("feishu-image://"):
        bare = raw_url[len("feishu-image://") :]
        return f"/api/v1/intheloop/feishu-image?token={quote(bare)}"
    if raw_url.startswith("public-image://"):
        bare = raw_url[len("public-image://") :]
        return f"/api/v1/intheloop/public-image?token={quote(bare)}"
    return raw_url


def render_intheloop_html(
    article: InTheLoopArticle,
    *,
    preview: bool = False,
) -> str:
    """Render the fixed InTheLoop WeChat HTML."""
    if preview:
        article = article.model_copy(deep=True)
        for block in article.blocks:
            if block.type == "image" and block.url:
                block.url = _preview_src(block.url)
    wrap_css = (
        "box-sizing:border-box;max-width:677px;margin:0 auto;padding:0;"
        f"{_BODY_FONT_CSS}color:rgb(0,0,0);"
    )
    opening_blocks, body_blocks = _split_opening_blocks(article)
    return (
        f'<section class="intheloop-article"{_style_attr(wrap_css)}>'
        f"{_article_opening_html(article)}"
        f"{_render_opening_blocks(opening_blocks)}"
        f"{_body_html(body_blocks, preview=preview)}"
        f"{_footer_html(article, preview=preview)}"
        "</section>"
    )
