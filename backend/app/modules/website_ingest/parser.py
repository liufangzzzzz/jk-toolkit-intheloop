from __future__ import annotations

import asyncio
import io
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import mammoth
from bs4 import BeautifulSoup, Tag

from .assets import save_asset
from .models import WebsiteImportArticle

_MAX_DOCUMENT_BYTES = 30 * 1024 * 1024
_MAX_IMAGE_BYTES = 15 * 1024 * 1024
_WECHAT_HOSTS = {"mp.weixin.qq.com"}
_ALLOWED_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "em", "i", "u", "s",
    "blockquote", "ul", "ol", "li", "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    "img", "a", "br", "hr", "figure", "figcaption", "span", "section", "div", "sup", "sub",
}
_DROP_TAGS = {"script", "style", "noscript", "iframe", "object", "embed", "form", "input", "button"}
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
    haystack = f" {title} {abstract} {_plain_text(content_html)[:8000]} ".lower()
    tags = [label for label, needles in _TAG_RULES if any(needle.lower() in haystack for needle in needles)]
    return (tags or ["In The Loop"])[:5]


def _safe_http_url(raw: str, *, base_url: str = "") -> str:
    value = urljoin(base_url, (raw or "").strip())
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.hostname else ""


def _sanitize_fragment(fragment: str) -> str:
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
        node.attrs = allowed
    return str(soup)


async def _download_image(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    try:
        response = await client.get(url)
        response.raise_for_status()
        raw = response.content
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if not content_type.startswith("image/") or not raw or len(raw) > _MAX_IMAGE_BYTES:
            return url, ""
        return url, save_asset(raw, content_type, suffix=urlparse(url).path)
    except Exception:
        return url, ""


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
        image_map = {url: asset for url, asset in downloaded if asset}
        for image, original_url in zip(image_nodes, image_urls):
            asset = image_map.get(original_url)
            if asset:
                image["src"] = asset
                for key in list(image.attrs):
                    if key not in {"src", "alt"}:
                        image.attrs.pop(key, None)
            else:
                image.decompose()
        cover_meta = soup.find("meta", attrs={"property": "og:image"})
        cover_url = _safe_http_url(str(cover_meta.get("content") if cover_meta else ""), base_url=str(response.url))
        cover_asset = image_map.get(cover_url, "")
        if cover_url and not cover_asset:
            _url, cover_asset = await _download_image(client, cover_url)
    warnings: list[str] = []
    failed_images = len(unique_urls) - len(image_map)
    if failed_images:
        warnings.append(f"有 {failed_images} 张微信图片未能下载，已从正文中移除")
    video_count = len(content.find_all(["video", "iframe"]))
    if video_count:
        warnings.append(f"检测到 {video_count} 个视频模块，官网同步暂不自动上传视频")
    cleaned = _sanitize_fragment(str(content))
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
    )


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

    def convert_image(image) -> dict[str, str]:
        with image.open() as image_file:
            reference = save_asset(image_file.read(), image.content_type)
        assets.append(reference)
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
    cleaned = _sanitize_fragment(str(soup))
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
    content = re.sub(
        r'ingest-asset://([a-f0-9]{32}\.[a-z0-9]{1,8})',
        r'/api/v1/website-import/assets/\1',
        article.content_html,
    )
    return (
        '<!doctype html><html><head><meta charset="utf-8"><style>'
        'body{margin:0;padding:36px;font:16px/1.8 Arial,"PingFang SC",sans-serif;color:#202020}'
        'article{max-width:760px;margin:auto}h1{font-size:34px;line-height:1.25}h2{margin-top:36px}'
        'img{display:block;max-width:100%;height:auto;margin:22px auto}table{width:100%;border-collapse:collapse}'
        'td,th{padding:8px;border:1px solid #ddd}blockquote{margin:20px 0;padding-left:18px;border-left:3px solid #111;color:#555}'
        '</style></head><body><article><h1>'
        + article.title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        + '</h1>' + content + '</article></body></html>'
    )
