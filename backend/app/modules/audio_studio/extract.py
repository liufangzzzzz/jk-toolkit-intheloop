"""Text-only imports; never downloads audio, images, or executes page scripts."""
import asyncio
import ipaddress
import socket
from urllib.parse import urlparse, urljoin
import httpx
from bs4 import BeautifulSoup

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

async def extract_url(url: str):
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
    account = soup.select_one('#js_name')
    publisher = account.get_text(' ',strip=True) if account else ''
    brand = 'linkstart' if '开始连接' in publisher or 'linkstart' in publisher.lower() else 'geekpark' if '极客公园' in publisher or urlparse(url).hostname in ('geekpark.net','www.geekpark.net','about.geekpark.net') else 'intheloop' if 'intheloop' in publisher.lower().replace(' ','') else None
    return {'source_account':publisher[:180],'brand':brand,'title': title[:250], 'summary': description.get('content', '') if description else '',
            'body': body, 'notice': '已提取原文文字。中文保留原链接；请选择模型生成英文，再编辑并分别发布。图片和音频未导入。'}
