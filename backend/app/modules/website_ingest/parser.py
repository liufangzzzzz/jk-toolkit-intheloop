from __future__ import annotations

import asyncio
import base64
import io
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import mammoth
from bs4 import BeautifulSoup, Tag
import tinycss2

from .assets import read_asset, save_asset
from .models import WebsiteImageIssue, WebsiteImportArticle

_MAX_DOCUMENT_BYTES = 30 * 1024 * 1024
_MAX_IMAGE_BYTES = 15 * 1024 * 1024
_WECHAT_HOSTS = {"mp.weixin.qq.com"}
_ALLOWED_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "em", "i", "u", "s",
    "blockquote", "ul", "ol", "li", "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    "img", "a", "br", "hr", "figure", "figcaption", "span", "section", "div", "sup", "sub",
}
_DROP_TAGS = {"script", "style", "noscript", "iframe", "object", "embed", "form", "input", "button"}
_SAFE_STYLE_PROPERTIES = {
    "background", "background-color", "background-image", "border", "border-color",
    "border-radius", "color", "font-style", "font-weight", "height", "letter-spacing",
    "line-height", "margin", "margin-bottom", "margin-left", "margin-right", "margin-top",
    "max-height", "max-width", "padding", "padding-bottom", "padding-left", "padding-right",
    "padding-top", "text-align", "text-decoration", "vertical-align", "width",
}
_FORBIDDEN_STYLE_VALUE = re.compile(r"(?:url\s*\(|expression\s*\(|javascript:|@import|var\s*\()", re.I)
_TAG_RULES = [
    ("具身智能", ("具身智能", "embodied ai", "embodied intelligence")),
    ("人形机器人", ("人形机器人", "humanoid")),
    ("机器人", ("机器人", "robot")),
    ("人工智能", ("人工智能", " ai ", "大模型", "模型")),
    ("自动驾驶", ("自动驾驶", "智驾")),
    ("芯片", ("芯片", "gpu", "算力")),
    ("创业", ("创业", "创始人")),
    ("融资", ("融资", "投资", "资本")),
]


def _plain_text(value: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)).strip()


def suggest_tags(title: str, abstract: str, content_html: str) -> list[str]:
    source = f"{title} {abstract} {_plain_text(content_html)[:8000]}"
    haystack = f" {source} ".lower()
    tags: list[str] = []

    def add(value: str) -> None:
        cleaned = re.sub(r"\s+", " ", value).strip(" ，。；：:、（）()《》\"'")
        if cleaned and cleaned not in tags:
            tags.append(cleaned)

    generic = {"人工智能", "具身智能", "人形机器人", "机器人", "科技公司", "有限公司"}
    company_pattern = re.compile(
        r"(?<![\u4e00-\u9fff])([A-Z][A-Za-z0-9.+-]*(?:\s+[A-Z][A-Za-z0-9.+-]*){0,3})(?=[\s，。；：:、（）()]|$)"
        r"|([\u4e00-\u9fffA-Za-z0-9]{2,14}(?:科技|智能|机器人|集团|资本|创投|研究院|实验室|公司))"
    )
    for match in company_pattern.finditer(source):
        candidate = match.group(1) or match.group(2) or ""
        candidate = re.sub(r"\s+(?:CEO|CTO|COO|创始人|董事长|总裁)$", "", candidate, flags=re.I)
        if (
            candidate not in generic
            and not candidate.isdigit()
            and not re.search(r"(?:表示|认为|进入|接受|发布|谈|这是一|一篇|一种|一个|具身|人形|人工|行业|文章|测试)", candidate)
        ):
            add(candidate)
        if len(tags) >= 6:
            break

    person_patterns = [
        re.compile(r"(?:创始人|联合创始人|CEO|董事长|总裁|负责人|作者|嘉宾)[\s：:]*([\u4e00-\u9fff]{2,4}?)(?=表示|认为|说|谈|接受|出席|发布|加入|[\s，。；：:]|$)"),
        re.compile(r"(?:^|[\n。！？])([\u4e00-\u9fff]{2,4})[：:]"),
    ]
    for pattern in person_patterns:
        for match in pattern.finditer(source):
            add(match.group(1))
            if len(tags) >= 8:
                break

    for label, needles in _TAG_RULES:
        if any(needle.lower() in haystack for needle in needles):
            add(label)
    return (tags or ["In The Loop"])[:10]


def _safe_http_url(raw: str, *, base_url: str = "") -> str:
    value = urljoin(base_url, (raw or "").strip())
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.hostname else ""


def _safe_style(raw: str, node_name: str) -> str:
    safe: list[str] = []
    for declaration in tinycss2.parse_declaration_list(raw or "", skip_comments=True, skip_whitespace=True):
        if declaration.type != "declaration" or declaration.lower_name not in _SAFE_STYLE_PROPERTIES:
            continue
        value = tinycss2.serialize(declaration.value).strip()
        if not value or _FORBIDDEN_STYLE_VALUE.search(value):
            continue
        name = declaration.lower_name
        if name in {"width", "height", "max-width", "max-height"} and not re.fullmatch(
            r"(?:auto|none|\d+(?:\.\d+)?(?:px|%|em|rem|vw|vh))", value, re.I
        ):
            continue
        safe.append(f"{name}:{value}")
    if node_name in {"h1", "h2"}:
        safe = [item for item in safe if not item.startswith(("font-size:", "line-height:"))]
        safe.extend(["font-size:18px", "line-height:1.55"])
    elif node_name in {"h3", "h4", "h5", "h6"}:
        safe = [item for item in safe if not item.startswith(("font-size:", "line-height:"))]
        safe.extend(["font-size:17px", "line-height:1.55"])
    return ";".join(dict.fromkeys(safe))


def sanitize_fragment(fragment: str) -> str:
    soup = BeautifulSoup(fragment or "", "html.parser")
    for node in list(soup.find_all(_DROP_TAGS)):
        node.decompose()
    for node in list(soup.find_all(True)):
        if node.name not in _ALLOWED_TAGS:
            node.unwrap()
            continue
        allowed: dict[str, str] = {}
        if node.name == "a":
            href = _safe_http_url(str(node.get("href") or ""))
            if href:
                allowed = {"href": href, "target": "_blank", "rel": "noreferrer"}
        elif node.name == "img":
            src = str(node.get("src") or "")
            if src.startswith("ingest-asset://"):
                allowed = {"src": src, "alt": str(node.get("alt") or "")[:300]}
            else:
                node.decompose()
                continue
        elif node.name in {"td", "th"}:
            for key in ("colspan", "rowspan"):
                raw = str(node.get(key) or "")
                if raw.isdigit():
                    allowed[key] = raw
        style = _safe_style(str(node.get("style") or ""), node.name)
        if style:
            allowed["style"] = style
        node.attrs = allowed
    return str(soup)


async def _download_image(client: httpx.AsyncClient, url: str) -> tuple[str, str, str]:
    try:
        response = await client.get(url)
        response.raise_for_status()
        raw = response.content
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if not content_type.startswith("image/") or not raw or len(raw) > _MAX_IMAGE_BYTES:
            return url, "", "返回内容不是有效图片，或图片超过 15MB"
        return url, save_asset(raw, content_type, suffix=urlparse(url).path), ""
    except Exception as exc:
        return url, "", str(exc)[:160] or "图片下载失败"


async def parse_wechat_url(source_url: str) -> WebsiteImportArticle:
    parsed_url = urlparse(source_url.strip())
    if parsed_url.scheme not in {"http", "https"} or (parsed_url.hostname or "").lower() not in _WECHAT_HOSTS:
        raise ValueError("请输入 mp.weixin.qq.com 的已发布文章链接")
    headers = {
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "accept-language": "zh-CN,zh;q=0.9",
    }
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as client:
        response = await client.get(source_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        content = soup.select_one("#js_content")
        if not content:
            raise ValueError("没有读取到微信文章正文，链接可能失效或需要验证")
        title_node = soup.select_one("#activity-name")
        title = title_node.get_text(" ", strip=True) if title_node else ""
        if not title:
            title = str((soup.find("meta", attrs={"property": "og:title"}) or {}).get("content") or "").strip()
        if not title:
            raise ValueError("没有读取到微信文章标题")
        description_meta = soup.find("meta", attrs={"name": "description"})
        abstract = str(description_meta.get("content") if description_meta else "").strip()
        image_urls: list[str] = []
        image_nodes: list[Tag] = []
        for image in content.find_all("img"):
            raw_src = str(image.get("data-src") or image.get("src") or "")
            resolved = _safe_http_url(raw_src, base_url=str(response.url))
            if resolved:
                image_urls.append(resolved)
                image_nodes.append(image)
        unique_urls = list(dict.fromkeys(image_urls))
        downloaded = await asyncio.gather(*[_download_image(client, url) for url in unique_urls])
        image_map = {url: asset for url, asset, _error in downloaded if asset}
        error_map = {url: error for url, asset, error in downloaded if not asset}
        image_issues: list[WebsiteImageIssue] = []
        for index, (image, original_url) in enumerate(zip(image_nodes, image_urls), start=1):
            asset = image_map.get(original_url)
            if asset:
                image["src"] = asset
                image["data-import-index"] = str(index)
            else:
                label = str(image.get("alt") or "").strip() or f"第 {index} 张图片"
                image_issues.append(WebsiteImageIssue(
                    index=index,
                    label=label[:100],
                    source_url=original_url,
                    message=error_map.get(original_url) or "图片下载失败",
                ))
                image.decompose()
        cover_meta = soup.find("meta", attrs={"property": "og:image"})
        cover_url = _safe_http_url(str(cover_meta.get("content") if cover_meta else ""), base_url=str(response.url))
        cover_asset = image_map.get(cover_url, "")
        if cover_url and not cover_asset:
            _url, cover_asset, _error = await _download_image(client, cover_url)
    warnings: list[str] = []
    failed_images = len(unique_urls) - len(image_map)
    if failed_images:
        warnings.append(f"有 {failed_images} 张微信图片未能下载；下方已列出位置和原图链接，可手动补回")
    video_count = len(content.find_all(["video", "iframe"]))
    if video_count:
        warnings.append(f"检测到 {video_count} 个视频模块，官网同步暂不自动上传视频")
    cleaned = sanitize_fragment(str(content))
    if not abstract:
        abstract = _plain_text(cleaned)[:150]
    if not cover_asset:
        first_image = BeautifulSoup(cleaned, "html.parser").find("img")
        cover_asset = str(first_image.get("src") or "") if first_image else ""
    tags = suggest_tags(title, abstract, cleaned)
    return WebsiteImportArticle(
        title=title,
        abstract=abstract[:500],
        content_html=cleaned,
        tags=tags,
        cover_asset=cover_asset,
        source_type="wechat_url",
        source_ref=source_url.strip(),
        warnings=warnings,
        image_issues=image_issues,
    )


def _image_dimensions(raw: bytes) -> tuple[int, int] | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 24:
        return struct.unpack(">II", raw[16:24])
    if raw.startswith((b"GIF87a", b"GIF89a")) and len(raw) >= 10:
        return struct.unpack("<HH", raw[6:10])
    if raw.startswith(b"\xff\xd8"):
        position = 2
        while position + 9 < len(raw):
            if raw[position] != 0xFF:
                position += 1
                continue
            marker = raw[position + 1]
            position += 2
            if marker in {0xD8, 0xD9}:
                continue
            if position + 2 > len(raw):
                break
            size = int.from_bytes(raw[position:position + 2], "big")
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF} and position + 7 < len(raw):
                return int.from_bytes(raw[position + 5:position + 7], "big"), int.from_bytes(raw[position + 3:position + 5], "big")
            position += max(size, 2)
    return None


def _normalize_compact_heading_images(soup: BeautifulSoup, dimensions: dict[str, tuple[int, int]]) -> None:
    for image in soup.find_all("img"):
        source = str(image.get("src") or "")
        size = dimensions.get(source)
        if not size or not size[1] or not (0.7 <= size[0] / size[1] <= 1.3):
            continue
        parent = image.parent if isinstance(image.parent, Tag) else image
        next_node = parent.find_next_sibling()
        while isinstance(next_node, Tag) and not next_node.get_text(" ", strip=True) and not next_node.find("img"):
            next_node = next_node.find_next_sibling()
        text = next_node.get_text(" ", strip=True) if isinstance(next_node, Tag) else ""
        is_heading = isinstance(next_node, Tag) and next_node.name in {"h1", "h2", "h3", "h4", "h5", "h6"}
        is_short_bold = isinstance(next_node, Tag) and bool(next_node.find(["strong", "b"])) and 0 < len(text) <= 80
        if is_heading or is_short_bold:
            image["style"] = "width:50px;height:auto;max-width:50px;margin-left:auto;margin-right:auto"


def _convert_legacy_doc(raw: bytes, filename: str) -> bytes:
    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if not executable:
        raise ValueError("当前环境尚未安装 LibreOffice，暂时无法读取 .doc 文件")
    with tempfile.TemporaryDirectory(prefix="itl-doc-") as temp_dir:
        source = Path(temp_dir) / (Path(filename).name or "document.doc")
        source.write_bytes(raw)
        process = subprocess.run(
            [executable, "--headless", "--convert-to", "docx", "--outdir", temp_dir, str(source)],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        converted = source.with_suffix(".docx")
        if process.returncode != 0 or not converted.is_file():
            raise ValueError(".doc 转换失败，请确认文件未损坏")
        return converted.read_bytes()


def parse_word_file(raw: bytes, filename: str) -> WebsiteImportArticle:
    if not raw or len(raw) > _MAX_DOCUMENT_BYTES:
        raise ValueError("Word 文件为空或超过 30MB")
    suffix = Path(filename or "").suffix.lower()
    if suffix not in {".docx", ".doc"}:
        raise ValueError("只支持 .docx 或 .doc 文件")
    source_type = "doc" if suffix == ".doc" else "docx"
    docx_bytes = _convert_legacy_doc(raw, filename) if suffix == ".doc" else raw
    assets: list[str] = []
    dimensions: dict[str, tuple[int, int]] = {}

    def convert_image(image) -> dict[str, str]:
        with image.open() as image_file:
            image_bytes = image_file.read()
            reference = save_asset(image_bytes, image.content_type)
        assets.append(reference)
        size = _image_dimensions(image_bytes)
        if size:
            dimensions[reference] = size
        return {"src": reference}

    result = mammoth.convert_to_html(
        io.BytesIO(docx_bytes),
        convert_image=mammoth.images.img_element(convert_image),
    )
    soup = BeautifulSoup(result.value, "html.parser")
    heading = soup.find(["h1", "h2"])
    title = heading.get_text(" ", strip=True) if heading else Path(filename).stem
    if heading:
        heading.decompose()
    _normalize_compact_heading_images(soup, dimensions)
    cleaned = sanitize_fragment(str(soup))
    abstract = _plain_text(cleaned)[:150]
    warnings = [str(message.message) for message in result.messages if getattr(message, "message", "")]
    tags = suggest_tags(title, abstract, cleaned)
    return WebsiteImportArticle(
        title=title or Path(filename).stem or "未命名文档",
        abstract=abstract,
        content_html=cleaned,
        tags=tags,
        cover_asset=assets[0] if assets else "",
        source_type=source_type,
        source_ref=filename,
        warnings=warnings,
    )


def render_preview(article: WebsiteImportArticle) -> str:
    soup = BeautifulSoup(article.content_html, "html.parser")
    for image in soup.find_all("img"):
        reference = str(image.get("src") or "")
        if not reference.startswith("ingest-asset://"):
            continue
        asset = read_asset(reference)
        if not asset:
            continue
        raw, _filename, content_type = asset
        image["data-asset-ref"] = reference
        image["src"] = f"data:{content_type};base64,{base64.b64encode(raw).decode('ascii')}"
    content = str(soup)
    return (
        '<!doctype html><html><head><meta charset="utf-8"><style>'
        'body{margin:0;padding:28px;font:16px/1.75 Arial,"PingFang SC",sans-serif;color:#202020}'
        'article{max-width:760px;margin:auto}article>h1{font-size:28px;line-height:1.35;margin:0 0 30px}'
        '#website-content h1,#website-content h2{font-size:18px!important;line-height:1.55!important;margin:28px 0 20px}'
        '#website-content h3,#website-content h4{font-size:17px!important;line-height:1.55!important}'
        '#website-content p{margin:0 0 20px}img{display:block;max-width:100%;height:auto;margin:24px auto}'
        'table{width:100%;border-collapse:collapse}'
        'td,th{padding:8px;border:1px solid #ddd}blockquote{margin:20px 0;padding-left:18px;border-left:3px solid #111;color:#555}'
        '#website-content[contenteditable="true"]{outline:2px solid #9a83fb;outline-offset:10px}'
        '</style></head><body><article><h1>'
        + article.title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        + '</h1><div id="website-content">' + content + '</div></article></body></html>'
    )
