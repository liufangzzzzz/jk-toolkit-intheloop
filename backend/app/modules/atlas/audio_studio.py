"""Isolated audio/transcript workspace. Failures here must not affect publishing routes."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ...auth import require_auth
from . import store
from .extract import extract_url
from app.ai_gateway import connection, model_options
from ..website_ingest.parser import parse_word_file

router = APIRouter(prefix='/api/v1/audio-studio', dependencies=[Depends(require_auth)])
_XYZ = re.compile(r'xiaoyuzhoufm\.com/episodes?/([0-9a-fA-F]{24})')
_BVID = re.compile(r'(BV[0-9A-Za-z]{10})', re.I)
_FEISHU_MINUTE = re.compile(r'/minutes/([0-9A-Za-z_-]+)', re.I)
_TEXT_EXT = {'.txt', '.md', '.srt', '.vtt'}
_DOC_EXT = {'.doc', '.docx'}
_AUDIO_EXT = {'.mp3', '.m4a', '.wav', '.aac', '.ogg', '.flac', '.mp4', '.mov'}
_MAX_BYTES = 60 * 1024 * 1024
_ARTICLE_SKILL_PATH = Path(__file__).with_name('default_audio_article_skill.md')


def _initial_article_skill() -> str:
    try:
        return _ARTICLE_SKILL_PATH.read_text(encoding='utf-8').strip()
    except OSError:
        return '根据清洗后的逐字稿生成一篇准确、可编辑的中文采访稿，不添加原文没有的信息。'

DEFAULT_SKILLS = {
    'clean': '''整理播客逐字稿。保留说话人的意思、事实、数字和语气，去掉无意义口头重复，但不要改写成文章。明显可能听错、专名不确定或上下文无法确认的片段必须用 [[?原片段?]] 标出。不要凭空纠正。输出严格 JSON：{"cleaned":"...","uncertain":["..."]}。''',
    'simple': '''根据逐字稿写一份简洁的内容沉淀，使用清楚的中文，保留核心观点、重要事实和有价值的例子。不要营销化，不要添加原文没有的信息。输出严格 JSON：{"simple":"..."}。''',
    'article': _initial_article_skill(),
}


class UrlInput(BaseModel):
    url: str = Field(min_length=1, max_length=4000)


class ProcessInput(BaseModel):
    model: str = Field(min_length=1)
    title: str = Field(default='', max_length=300)
    transcript: str = Field(min_length=1, max_length=240000)


class ArticleInput(ProcessInput):
    simple: str = Field(default='', max_length=80000)


class CorrectionInput(BaseModel):
    model: str = Field(min_length=1)
    instruction: str = Field(min_length=2, max_length=2000)
    cleaned: str = Field(min_length=1, max_length=240000)
    simple: str = Field(default='', max_length=100000)


class FeishuExportInput(BaseModel):
    title: str = Field(default='音频整理', max_length=300)
    content: str = Field(min_length=1, max_length=500000)


class SkillInput(BaseModel):
    clean: str = Field(min_length=20, max_length=50000)
    simple: str = Field(min_length=20, max_length=50000)
    article: str = Field(min_length=20, max_length=50000)


class ProjectInput(BaseModel):
    revision: int = 0
    title: str = Field(default='未命名音频', max_length=300)
    source_url: str = Field(default='', max_length=4000)
    source_kind: str = Field(default='text', max_length=40)
    transcript: str = Field(default='', max_length=300000)
    cleaned: str = Field(default='', max_length=300000)
    simple: str = Field(default='', max_length=100000)
    article_title: str = Field(default='', max_length=300)
    article_summary: str = Field(default='', max_length=10000)
    article_body: str = Field(default='', max_length=300000)


def _skill(name: str) -> str:
    return store.get_setting('audio-skill-' + name, DEFAULT_SKILLS[name])


def _feishu_user_configured() -> bool:
    return bool(
        os.environ.get('FEISHU_USER_ACCESS_TOKEN', '').strip()
        or os.environ.get('FEISHU_USER_REFRESH_TOKEN', '').strip()
        or store.get_setting('feishu-user-refresh-token', '').strip()
    )


async def _feishu_user_token(client: httpx.AsyncClient) -> str:
    direct = os.environ.get('FEISHU_USER_ACCESS_TOKEN', '').strip()
    if direct:
        return direct
    refresh_token = store.get_setting('feishu-user-refresh-token', '').strip() or os.environ.get('FEISHU_USER_REFRESH_TOKEN', '').strip()
    app_id = os.environ.get('FEISHU_APP_ID', '').strip()
    app_secret = os.environ.get('FEISHU_APP_SECRET', '').strip()
    if not refresh_token or not app_id or not app_secret:
        raise HTTPException(503, '尚未配置飞书用户授权。需要用户 access token，或 App ID、Secret 与用户 refresh token。')
    api_base = os.environ.get('FEISHU_API_BASE', 'https://open.feishu.cn/open-apis').rstrip('/')
    response = await client.post(api_base + '/authen/v2/oauth/token', json={
        'grant_type': 'refresh_token',
        'client_id': app_id,
        'client_secret': app_secret,
        'refresh_token': refresh_token,
    })
    response.raise_for_status()
    payload = response.json()
    if payload.get('code') not in (None, 0):
        raise ValueError(str(payload.get('message') or payload.get('msg') or '用户授权刷新失败'))
    token = str(payload.get('access_token') or (payload.get('data') or {}).get('access_token') or '')
    renewed = str(payload.get('refresh_token') or (payload.get('data') or {}).get('refresh_token') or '')
    if not token:
        raise ValueError('飞书没有返回用户 access token')
    if renewed and renewed != refresh_token:
        store.set_setting('feishu-user-refresh-token', renewed)
    return token


async def _feishu_minute_transcript(url: str) -> dict:
    match = _FEISHU_MINUTE.search(url)
    if not match:
        raise ValueError('妙记链接中没有识别到 minute token')
    api_base = os.environ.get('FEISHU_API_BASE', 'https://open.feishu.cn/open-apis').rstrip('/')
    minute_token = match.group(1)
    async with httpx.AsyncClient(timeout=60) as client:
        token = await _feishu_user_token(client)
        headers = {'Authorization': 'Bearer ' + token}
        info_response = await client.get(api_base + f'/minutes/v1/minutes/{minute_token}', headers=headers)
        info_response.raise_for_status()
        info = info_response.json()
        if info.get('code') not in (None, 0):
            raise ValueError(str(info.get('msg') or '妙记信息读取失败'))
        minute = ((info.get('data') or {}).get('minute') or {})
        transcript_response = await client.get(
            api_base + f'/minutes/v1/minutes/{minute_token}/transcript',
            headers=headers,
            params={'need_speaker': 'true', 'need_timestamp': 'true', 'file_format': 'txt'},
        )
        transcript_response.raise_for_status()
        transcript = transcript_response.text.strip()
        if not transcript:
            raise ValueError('妙记没有返回逐字稿')
    return {'title': str(minute.get('title') or ''), 'transcript': transcript, 'source_kind': 'feishu', 'needs_ai': False}


def _run(args: list[str], timeout=180) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise ValueError((result.stderr or result.stdout or '读取失败').strip()[:500])
    return result.stdout.strip()


def _executable(name: str, env_name: str = '') -> str | None:
    configured = os.environ.get(env_name, '').strip() if env_name else ''
    candidates = [configured, shutil.which(name) or '']
    if name == 'yt-dlp':
        candidates.extend(['/opt/homebrew/bin/yt-dlp', '/usr/local/bin/yt-dlp'])
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _xyz_transcript(url: str) -> dict:
    match = _XYZ.search(url)
    exe = _executable('xyz', 'XYZ_BIN') or _executable('xiaoyuzhou', 'XYZ_BIN')
    if not match or not exe:
        raise ValueError('当前服务器尚未连接小宇宙官方 transcript 工具；可上传导出文字或录音。')
    episode = match.group(1)
    detail = json.loads(_run([exe, 'episode', episode]) or '{}')
    def media_id(value):
        if isinstance(value, dict):
            for key in ('transcript_media_id', 'transcriptMediaId', 'media_id', 'mediaId'):
                if isinstance(value.get(key), str) and value[key]: return value[key]
            for child in value.values():
                found = media_id(child)
                if found: return found
        if isinstance(value, list):
            for child in value:
                found = media_id(child)
                if found: return found
        return None
    mid = media_id(detail)
    if not mid: raise ValueError('这期小宇宙节目没有返回官方 transcript。')
    text = _run([exe, 'transcript', episode, '--media-id', mid, '--format', 'plain', '--text'])
    return {'title': detail.get('title', ''), 'transcript': text, 'source_kind': 'xiaoyuzhou', 'needs_ai': False}


def _vtt_text(raw: str) -> str:
    lines, result, previous = raw.splitlines(), [], ''
    for line in lines:
        value = re.sub(r'<[^>]+>', '', line).strip()
        if not value or value == 'WEBVTT' or '-->' in value or re.fullmatch(r'\d+', value): continue
        if value != previous: result.append(value)
        previous = value
    return '\n'.join(result)


def _video_transcript(url: str) -> dict:
    exe = _executable('yt-dlp', 'YTDLP_BIN')
    if not exe: raise ValueError('当前服务器没有视频字幕读取组件；可粘贴字幕、上传字幕文件或录音。')
    with tempfile.TemporaryDirectory() as folder:
        output = str(Path(folder) / '%(id)s')
        _run([exe, '--skip-download', '--write-subs', '--write-auto-subs', '--sub-langs', 'zh.*,en.*', '--sub-format', 'vtt', '-o', output, url], 240)
        files = list(Path(folder).glob('*.vtt'))
        if not files: raise ValueError('这个视频没有可读取的字幕；如需从音频识别，请选择模型。')
        text = _vtt_text(files[0].read_text(errors='ignore'))
        return {'title': '', 'transcript': text, 'source_kind': 'video', 'needs_ai': False}


async def _bilibili_transcript(url: str) -> dict:
    match = _BVID.search(url)
    if not match:
        return _video_transcript(url)
    bvid = match.group(1)
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.bilibili.com/'}
    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            info = await client.get('https://api.bilibili.com/x/web-interface/view', params={'bvid': bvid})
            info.raise_for_status()
            data = info.json().get('data') or {}
            cid = data.get('cid') or ((data.get('pages') or [{}])[0].get('cid'))
            if not cid: raise ValueError('没有读取到视频分集信息')
            player = await client.get('https://api.bilibili.com/x/player/v2', params={'bvid': bvid, 'cid': cid})
            player.raise_for_status()
            subtitles = (((player.json().get('data') or {}).get('subtitle') or {}).get('subtitles') or [])
            if not subtitles: raise ValueError('视频没有返回可用字幕')
            preferred = next((item for item in subtitles if str(item.get('lan', '')).lower().startswith('zh')), subtitles[0])
            subtitle_url = str(preferred.get('subtitle_url') or '')
            if subtitle_url.startswith('//'): subtitle_url = 'https:' + subtitle_url
            if not subtitle_url.startswith('https://'): raise ValueError('字幕地址无效')
            response = await client.get(subtitle_url)
            response.raise_for_status()
            body = response.json().get('body') or []
            text = '\n'.join(str(item.get('content') or '').strip() for item in body if str(item.get('content') or '').strip())
            if not text: raise ValueError('字幕内容为空')
            return {'title': str(data.get('title') or ''), 'transcript': text, 'source_kind': 'bilibili', 'needs_ai': False}
    except Exception:
        # This fallback still uses --skip-download and only requests subtitle files.
        return _video_transcript(url)


async def _chat(model: str, system: str, text: str) -> dict:
    try: allowed = {item['id'] for item in await model_options()}
    except ValueError as exc: raise HTTPException(503, str(exc))
    if model not in allowed: raise HTTPException(422, '请选择已经配置的模型')
    key, base, _provider = connection()
    if not key or not base: raise HTTPException(503, '尚未配置模型接口')
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(base + '/chat/completions', headers={'Authorization': 'Bearer ' + key}, json={'model': model, 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': text}]})
            response.raise_for_status()
            raw = response.json()['choices'][0]['message']['content']
        return json.loads(raw.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip())
    except Exception as exc:
        raise HTTPException(502, '模型没有返回完整结果，原始文字仍然保留。') from exc


@router.get('/skills')
def skills(): return {name: _skill(name) for name in DEFAULT_SKILLS}


@router.get('/status')
def source_status():
    return {
        'feishu_app_configured': bool(os.environ.get('FEISHU_APP_ID', '').strip() and os.environ.get('FEISHU_APP_SECRET', '').strip()),
        'feishu_user_configured': _feishu_user_configured(),
        'skills_configured': all(bool(store.get_setting('audio-skill-' + name, '').strip()) for name in DEFAULT_SKILLS),
        'youtube_ready': bool(_executable('yt-dlp', 'YTDLP_BIN')),
        'xiaoyuzhou_ready': bool(_executable('xyz', 'XYZ_BIN') or _executable('xiaoyuzhou', 'XYZ_BIN')),
    }


@router.put('/skills')
def save_skills(body: SkillInput):
    for name in DEFAULT_SKILLS: store.set_setting('audio-skill-' + name, getattr(body, name).strip())
    return {'ok': True}


@router.get('/projects')
def projects(): return {'projects': store.audio_projects()}


@router.post('/projects')
def create_project(body: ProjectInput):
    data = body.model_dump()
    try: return store.save_audio_project(data)
    except ValueError as exc: raise HTTPException(409, str(exc))


@router.put('/projects/{record_id}')
def update_project(record_id: str, body: ProjectInput):
    data = body.model_dump()
    try: return store.save_audio_project(data, record_id)
    except ValueError as exc: raise HTTPException(409, str(exc))


@router.post('/import-url')
async def import_link(body: UrlInput):
    url = body.url.strip()
    is_feishu = any(x in url.lower() for x in ('feishu.cn', 'larksuite.com'))
    try:
        if is_feishu and _FEISHU_MINUTE.search(url) and _feishu_user_configured():
            return await _feishu_minute_transcript(url)
        if _XYZ.search(url): return _xyz_transcript(url)
        if any(host in url.lower() for host in ('bilibili.com', 'b23.tv')):
            return await _bilibili_transcript(url)
        if any(host in url.lower() for host in ('youtube.com', 'youtu.be')):
            return _video_transcript(url)
        extracted = await extract_url(url)
        text = extracted.get('body', '').strip()
        if len(text) < 200: raise ValueError('链接中没有读取到足够的文字。若这是私有飞书妙记，请先导出文字；若只有音频，请选择模型识别。')
        kind = 'feishu' if is_feishu else 'otter' if 'otter.ai' in url.lower() else 'web'
        return {'title': extracted.get('title', ''), 'transcript': text, 'source_kind': kind, 'needs_ai': False}
    except HTTPException: raise
    except Exception as exc:
        if is_feishu:
            raise HTTPException(422, '这个妙记链接需要飞书登录。它在你已登录的浏览器里能打开，但服务器没有你的浏览器登录状态。请将分享权限设为无需登录也可查看，或导出文字后粘贴/上传。') from exc
        raise HTTPException(422, str(exc)[:500]) from exc


@router.post('/import-file')
async def import_file(file: UploadFile = File(...), model: str = Form('')):
    name = file.filename or 'audio'
    ext = Path(name).suffix.lower()
    raw = await file.read(_MAX_BYTES + 1)
    if len(raw) > _MAX_BYTES: raise HTTPException(413, '文件请控制在 60 MB 以内')
    if ext in _TEXT_EXT:
        text = raw.decode('utf-8-sig', errors='replace')
        if ext == '.vtt': text = _vtt_text(text)
        return {'title': Path(name).stem, 'transcript': text, 'source_kind': 'file', 'needs_ai': False}
    if ext in _DOC_EXT:
        parsed = parse_word_file(raw, name)
        text = BeautifulSoup(parsed.content_html, 'html.parser').get_text('\n', strip=True)
        return {'title': parsed.title, 'transcript': text, 'source_kind': 'file', 'needs_ai': False}
    if ext not in _AUDIO_EXT: raise HTTPException(422, '支持音频、视频、TXT、Markdown、SRT、VTT、DOC 和 DOCX')
    if not model: return {'title': Path(name).stem, 'transcript': '', 'source_kind': 'audio', 'needs_ai': True, 'notice': '需要使用 AI 识别。选择模型后再次点击开始识别。'}
    try: allowed = {item['id'] for item in await model_options()}
    except ValueError as exc: raise HTTPException(503, str(exc))
    if model not in allowed: raise HTTPException(422, '请选择已经配置的模型')
    key, base, _provider = connection()
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            response = await client.post(base + '/audio/transcriptions', headers={'Authorization': 'Bearer ' + key}, data={'model': model}, files={'file': (name, raw, file.content_type or 'application/octet-stream')})
            response.raise_for_status()
            transcript = response.json().get('text', '')
        if not transcript: raise ValueError()
        return {'title': Path(name).stem, 'transcript': transcript, 'source_kind': 'audio', 'needs_ai': False}
    except Exception as exc:
        raise HTTPException(502, '所选模型未能完成音频识别。请换用支持音频转写的模型，原文件未保存。') from exc


@router.post('/process')
async def process(body: ProcessInput):
    source = f"标题：{body.title}\n\n逐字稿：\n{body.transcript}"
    cleaned = await _chat(body.model, _skill('clean'), source)
    clean_text = str(cleaned.get('cleaned', '')).strip()
    if not clean_text: raise HTTPException(502, '清洗结果不完整，原始文字仍然保留。')
    simple = await _chat(body.model, _skill('simple'), clean_text)
    return {'cleaned': clean_text, 'simple': str(simple.get('simple', '')).strip(), 'uncertain': cleaned.get('uncertain', [])}


@router.post('/correct')
async def correct(body: CorrectionInput):
    system = '''你是逐字稿纠错器。严格按照用户的自然语言指令，检查清洗版和简版中的同类识别错误并同步修正。原版不在本次纠错范围内。只修改指令明确要求修正的词、人名、公司名、产品名或术语；保持其余文字、段落、说话人、标点和 [[?不确定片段?]] 标记不变，不润色、不删减、不总结。输出严格 JSON，不要 Markdown 代码围栏：{"cleaned":"修正后的清洗版","simple":"修正后的简版"}。'''
    source = f"纠错指令：{body.instruction}\n\n清洗版：\n{body.cleaned}\n\n简版：\n{body.simple}"
    result = await _chat(body.model, system, source)
    cleaned = str(result.get('cleaned', '')).strip()
    if not cleaned:
        raise HTTPException(502, '纠错结果不完整，清洗版和简版均未改变。')
    return {
        'cleaned': cleaned,
        'simple': str(result.get('simple', body.simple)).strip(),
    }


@router.post('/export-feishu')
async def export_feishu(body: FeishuExportInput):
    api_base = os.environ.get('FEISHU_API_BASE', 'https://open.feishu.cn/open-apis').rstrip('/')
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            token = await _feishu_user_token(client)
            headers = {'Authorization': 'Bearer ' + token}
            document_response = await client.post(api_base + '/docx/v1/documents', headers=headers, json={'title': body.title or '音频整理'})
            document_response.raise_for_status()
            document = ((document_response.json().get('data') or {}).get('document') or {})
            document_id = str(document.get('document_id') or '')
            if not document_id: raise ValueError('飞书没有返回文档 ID')
            chunks: list[str] = []
            for paragraph in body.content.splitlines():
                if not paragraph.strip(): continue
                chunks.extend(paragraph[index:index + 1500] for index in range(0, len(paragraph), 1500))
            children = [{'block_type': 2, 'text': {'elements': [{'text_run': {'content': chunk}}]}} for chunk in chunks]
            for index in range(0, len(children), 50):
                block_response = await client.post(api_base + f'/docx/v1/documents/{document_id}/blocks/{document_id}/children', headers=headers, json={'children': children[index:index + 50]})
                block_response.raise_for_status()
        origin = os.environ.get('FEISHU_DOC_ORIGIN', 'https://geek.feishu.cn/docx').rstrip('/')
        return {'url': origin + '/' + document_id, 'document_id': document_id}
    except HTTPException: raise
    except Exception as exc:
        raise HTTPException(502, '飞书文档创建失败。请检查用户授权、云文档权限与 env 配置。') from exc


@router.post('/article')
async def article(body: ArticleInput):
    web_format = '''\n\n这是网页编辑器调用。忽略规则中创建 DOCX、写文件或返回多个附件的要求；请直接生成一份可继续编辑的稿件。输出严格 JSON，不要 Markdown 代码围栏：{"title":"标题","summary":"摘要","body":"正文"}。'''
    result = await _chat(body.model, _skill('article') + web_format, f"标题：{body.title}\n\n清洗稿：\n{body.transcript}")
    if not all(str(result.get(key, '')).strip() for key in ('title', 'body')):
        raise HTTPException(502, '稿件结果不完整，已有文字未改变。')
    return {key: str(result.get(key, '')).strip() for key in ('title', 'summary', 'body')}
