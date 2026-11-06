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
_GEEKPARK_IMAGE_HOSTS = {'imgslim.geekpark.net'}
_GEEKPARK_ID = re.compile(r'/(?:news|post|posts)/(\d+)(?:[/?#]|$)', re.I)
_IMAGE_LIMIT = 15 * 1024 * 1024


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
        media.append({'type':kind,'url':src,'alt':str(image.get('alt') or '')[:300],'caption':'','placement':'before_body'})
    return media


def _image_type(raw: bytes, declared: str) -> tuple[str, str] | None:
    content_type = (declared or '').split(';', 1)[0].lower()
    if raw.startswith(b'\xff\xd8\xff'): content_type = 'image/jpeg'
    elif raw.startswith(b'\x89PNG\r\n\x1a\n'): content_type = 'image/png'
    elif raw.startswith((b'GIF87a', b'GIF89a')): content_type = 'image/gif'
    elif raw.startswith(b'RIFF') and len(raw) >= 12 and raw[8:12] == b'WEBP': content_type = 'image/webp'
    if content_type not in {'image/jpeg','image/png','image/gif','image/webp'}: return None
    return content_type, 'gif' if content_type == 'image/gif' else 'image'


async def _download_public_image(client: httpx.AsyncClient, source: str) -> dict | None:
    url = source
    try:
        for _ in range(4):
            pinned, hostname, host = await public_target(url)
            async with client.stream('GET', pinned, headers={'Host':host}, extensions={'sni_hostname':hostname}) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get('location', ''))
                    continue
                response.raise_for_status()
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > _IMAGE_LIMIT: return None
                detected = _image_type(bytes(raw), response.headers.get('content-type', ''))
                if not detected: return None
                content_type, kind = detected
                return {'type':kind,'url':save_asset(bytes(raw), content_type),'alt':'','caption':'','placement':'before_body','inline_offsets':{}}
        return None
    except (ValueError, OSError, httpx.HTTPError):
        return None


async def _persist_html_media(value: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(value or '', 'html.parser')
    sources = []
    for image in soup.find_all('img')[:100]:
        source = str(image.get('data-src') or image.get('src') or '').strip()
        if source.startswith('ingest-asset://'):
            sources.append(source)
        elif source:
            resolved = urljoin(base_url, source)
            if resolved.startswith(('http://','https://')): sources.append(resolved)
    sources = list(dict.fromkeys(sources))
    durable = [source for source in sources if source.startswith('ingest-asset://')]
    remote = [source for source in sources if not source.startswith('ingest-asset://')]
    media = _html_media(''.join(f'<img src="{source}">' for source in durable))
    if remote:
        semaphore = asyncio.Semaphore(6)
        async with httpx.AsyncClient(timeout=25, follow_redirects=False, trust_env=False,
                                     headers={'User-Agent':'Mozilla/5.0','Accept':'image/avif,image/webp,image/png,image/gif,image/jpeg,*/*;q=0.5'}) as client:
            async def fetch(index, source):
                async with semaphore:
                    downloaded = await _download_public_image(client, source)
                    # GeekPark's image CDN is a durable public origin. Some
                    # deployments cannot reach it directly even though readers'
                    # browsers can. Do not silently discard those article images:
                    # keep the verified public URL as a display fallback.
                    if downloaded is None and (urlparse(source).hostname or '').lower() in _GEEKPARK_IMAGE_HOSTS:
                        path = urlparse(source).path.lower()
                        downloaded = {
                            'type': 'gif' if path.endswith('.gif') else 'image',
                            'url': source,
                            'alt': '',
                            'caption': '',
                            'placement': 'before_body',
                            'inline_offsets': {},
                        }
                    return index, downloaded
            tasks = [asyncio.create_task(fetch(index, source)) for index, source in enumerate(remote)]
            done, pending = await asyncio.wait(tasks, timeout=35)
            for task in pending: task.cancel()
            if pending: await asyncio.gather(*pending, return_exceptions=True)
            downloaded = sorted((task.result() for task in done if not task.cancelled() and not task.exception()), key=lambda result: result[0])
        media.extend(item for _index, item in downloaded if item)
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
                media.append({'type':'gif' if mime == 'image/gif' else 'image','url':reference,'alt':'','caption':'','placement':'before_body'})
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
    content_html = str(payload.get('content') or payload.get('content_html') or '')
    body = _html_text(content_html)
    if not title or len(body) < 40:
        raise ValueError('未提取到完整极客公园文章，请检查链接或直接粘贴正文')
    media = await _persist_html_media(content_html, url)
    copied = sum(str(item.get('url', '')).startswith('ingest-asset://') for item in media)
    fallback = len(media) - copied
    if media:
        media_notice = f'已读取 {len(media)} 个图片/GIF（{copied} 个已复制到本站'
        media_notice += f'，{fallback} 个使用极客公园原图链接' if fallback else ''
        media_notice += '）。'
    else:
        media_notice = '未读取到正文图片；若原文有图，请稍后重新提取或在媒体区手动上传。'
    return {
        'source_account': 'In The Loop',
        'brand': 'intheloop',
        'title': title[:250],
        'summary': summary,
        'body': body,
        'media': media,
        'notice': media_notice + '中文站展示原文、AI 阅读提示与原文链接；请选择模型生成英文并审核标签。',
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
    media = await _persist_html_media(str(content), url)
    return {'source_account':'In The Loop','brand':'intheloop','title': title[:250], 'summary': description.get('content', '') if description else '',
            'body': body, 'media': media, 'notice': f'已提取原文文字并保存 {len(media)} 个 JPG / PNG / GIF / WebP；请核对媒体与正文。'}
