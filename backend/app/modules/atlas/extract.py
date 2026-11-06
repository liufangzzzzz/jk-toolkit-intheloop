"""Safe article imports for text plus durable editorial media."""
import asyncio
import ipaddress
import os
import re
import socket
from urllib.parse import urlparse, urljoin
import httpx
from bs4 import BeautifulSoup
from ..website_ingest.assets import save_asset

_GEEKPARK_HOSTS = {'geekpark.net', 'www.geekpark.net'}
_GEEKPARK_ID = re.compile(r'/(?:news|post|posts)/(\d+)(?:[/?#]|$)', re.I)


def _html_text(value: str) -> str:
    soup = BeautifulSoup(value or '', 'html.parser')
    for node in soup.select('script,style,noscript,nav,footer,form,iframe,img,video'): node.decompose()
    return soup.get_text('\n', strip=True)


def _html_media(value: str) -> list[dict]:
    soup = BeautifulSoup(value or '', 'html.parser')
    media = []
    for image in soup.find_all('img'):
        src = str(image.get('src') or '').strip()
        if not src: continue
        kind = 'gif' if src.lower().split('?',1)[0].endswith('.gif') else 'image'
        media.append({'type':kind,'url':src,'alt':str(image.get('alt') or '')[:300],'caption':''})
    return media


async def extract_wechat_url(url: str):
    """Reuse the proven website parser and persist WeChat images/GIFs."""
    from ..website_ingest.parser import parse_wechat_url
    article = await parse_wechat_url(url, include_images=True)
    body = _html_text(article.content_html)
    if len(body) < 40:
        raise ValueError('未提取到完整微信文章，请确认链接可以公开访问')
    return {
        'source_account': 'In The Loop',
        'brand': 'intheloop',
        'title': article.title[:250],
        'summary': article.abstract,
        'body': body,
        'media': _html_media(article.content_html),
        'notice': '已读取中文原文及可访问的图片/GIF。请核对媒体、英文稿和标签后发布。',
    }


async def extract_feishu_url(url: str):
    """Copy public Feishu images out of the short-lived parser cache."""
    from agents.intheloop.feishu_parser import parse_feishu_document
    from agents.intheloop.feishu.public_image_store import fetch_public_image
    article = await parse_feishu_document(url)
    paragraphs, media = [], []
    for block in article.blocks:
        if block.type == 'image' and block.url:
            fetched = fetch_public_image(block.url)
            if fetched:
                raw, filename, mime = fetched
                reference = save_asset(raw, mime, suffix=filename)
                media.append({'type':'gif' if mime == 'image/gif' else 'image','url':reference,'alt':'','caption':''})
        elif block.type in {'heading','paragraph','question','answer','caption'} and block.content.strip():
            prefix = (block.speaker.strip() + '：') if block.speaker.strip() else ''
            paragraphs.append(prefix + block.content.strip())
    body = '\n\n'.join(paragraphs)
    if not article.title or len(body) < 20: raise ValueError('未提取到完整飞书文档，请确认链接已开放阅读权限')
    notice = f'已读取飞书正文及 {len(media)} 个图片/GIF。'
    if article.video_count: notice += f' 检测到 {article.video_count} 个视频附件，请在媒体区手动上传视频文件。'
    return {'source_account':'In The Loop','brand':'intheloop','title':article.title[:250],'summary':article.digest,'body':body,'media':media,'notice':notice}


async def extract_geekpark_url(url: str):
    """Read GeekPark's public content API because its public pages may return 403."""
    match = _GEEKPARK_ID.search(urlparse(url).path + '/')
    if not match:
        return await extract_url(url, specialized=False)
    record_id = match.group(1)
    base = os.environ.get('WEBSITE_GEEKPARK_API_BASE', 'https://mainssl.geekpark.net').rstrip('/')
    async with httpx.AsyncClient(timeout=25, follow_redirects=True, trust_env=False) as client:
        payload = None
        for kind, key in (('posts', 'post'), ('news', 'new')):
            response = await client.get(f'{base}/api/v1/{kind}/{record_id}')
            if response.status_code == 404:
                continue
            response.raise_for_status()
            candidate = response.json()
            payload = candidate.get(key) or candidate
            if isinstance(payload, dict):
                break
        if not isinstance(payload, dict):
            raise ValueError('极客公园官网没有找到这篇内容')
    title = str(payload.get('title') or '').strip()
    summary = str(payload.get('abstract') or payload.get('summary') or '').strip()
    body = _html_text(str(payload.get('content') or payload.get('content_html') or ''))
    if not title or len(body) < 40:
        raise ValueError('未提取到完整极客公园文章，请检查链接或直接粘贴正文')
    return {
        'source_account': 'In The Loop',
        'brand': 'intheloop',
        'title': title[:250],
        'summary': summary,
        'body': body,
        'notice': '已读取中文原文。中文站展示原文、AI 阅读提示与原文链接；请选择模型生成英文并审核标签。',
    }

async def public_target(url):
    parsed = urlparse(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,80,443):
        raise ValueError('请输入有效的公开文章链接')
    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme=='https' else 80), type=socket.SOCK_STREAM)
        ips = {x[4][0] for x in addresses}
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips): raise ValueError('只能提取公开网站文章')
    except OSError:
        raise ValueError('未能找到这个网站，请检查链接')
    address = sorted(ips)[0]
    # Pin the resolved address while retaining the original TLS server name.
    pinned = httpx.URL(url).copy_with(host=address)
    return pinned, parsed.hostname, parsed.netloc

async def extract_url(url: str, *, specialized: bool = True):
    hostname = (urlparse(url).hostname or '').lower()
    if specialized and hostname == 'mp.weixin.qq.com':
        return await extract_wechat_url(url)
    if specialized and hostname in _GEEKPARK_HOSTS:
        return await extract_geekpark_url(url)
    if specialized and (hostname == 'feishu.cn' or hostname.endswith('.feishu.cn')):
        return await extract_feishu_url(url)
    async with httpx.AsyncClient(timeout=25, follow_redirects=False, trust_env=False,
                                 headers={'User-Agent': 'Mozilla/5.0'}) as client:
        for _ in range(5):
            pinned, hostname, host = await public_target(url)
            async with client.stream('GET', pinned, headers={'Host':host}, extensions={'sni_hostname':hostname}) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get('location', ''))
                    continue
                response.raise_for_status()
                if 'html' not in response.headers.get('content-type', ''):
                    raise ValueError('链接不是文章网页，请粘贴文字或上传文档')
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 5 * 1024 * 1024: raise ValueError('页面过大，请粘贴文章正文')
                break
        else: raise ValueError('页面跳转过多，请使用最终文章链接')
    soup = BeautifulSoup(bytes(raw), 'html.parser')
    title_node = soup.select_one('#activity-name, h1')
    title_text = title_node.get_text(' ', strip=True) if title_node else ''
    for node in soup.select('script,style,noscript,nav,footer,form,iframe'): node.decompose()
    content = soup.select_one('#js_content, .article-content, .article_content, .post-content, article, main')
    if content is None: raise ValueError('未找到文章正文，原站可能需要验证，请直接粘贴文字')
    meta = soup.select_one('meta[property="og:title"]')
    title = title_text or (meta.get('content', '') if meta else '')
    body = content.get_text('\n', strip=True)
    if not title or len(body) < 40: raise ValueError('未提取到完整文章，请直接粘贴正文')
    description = soup.select_one('meta[name="description"]')
    return {'source_account':'In The Loop','brand':'intheloop','title': title[:250], 'summary': description.get('content', '') if description else '',
            'body': body, 'media': [], 'notice': '已提取原文文字。普通网站的媒体请在下方手动上传。'}
