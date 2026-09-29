"""Isolated audio/transcript workspace. Failures here must not affect publishing routes."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ...auth import require_auth
from ...document_text import parse_word_text
from . import store
from .extract import extract_url
from app.ai_gateway import connection, model_options

router = APIRouter(prefix='/api/v1/audio-studio', dependencies=[Depends(require_auth)])
_XYZ = re.compile(r'xiaoyuzhoufm\.com/episodes?/([0-9a-fA-F]{24})')
_BVID = re.compile(r'(BV[0-9A-Za-z]{10})', re.I)
_FEISHU_MINUTE = re.compile(r'/minutes/([0-9A-Za-z_-]+)', re.I)
_TEXT_EXT = {'.txt', '.md', '.srt', '.vtt'}
_DOC_EXT = {'.doc', '.docx'}
_AUDIO_EXT = {'.mp3', '.m4a', '.wav', '.aac', '.ogg', '.flac', '.mp4', '.mov'}
_MAX_BYTES = 60 * 1024 * 1024
_SKILL_PATHS = {
    'clean': Path(__file__).with_name('default_audio_clean_skill.md'),
    'simple': Path(__file__).with_name('default_audio_simple_skill.md'),
    'article': Path(__file__).with_name('default_audio_article_skill.md'),
}


def _initial_skill(name: str) -> str:
    try:
        return _SKILL_PATHS[name].read_text(encoding='utf-8').strip()
    except OSError:
        return '忠实处理完整逐字稿，保留事实、时间顺序、说话人和不确定性，不添加原文没有的信息。'

DEFAULT_SKILLS = {
    name: _initial_skill(name) for name in _SKILL_PATHS
}
_LEGACY_CLEAN_SKILL = '''整理播客逐字稿。保留说话人的意思、事实、数字和语气，去掉无意义口头重复，但不要改写成文章。明显可能听错、专名不确定或上下文无法确认的片段必须用 [[?原片段?]] 标出。不要凭空纠正。输出严格 JSON：{"cleaned":"...","uncertain":["..."]}。'''
_LEGACY_SIMPLE_SKILL = '''根据逐字稿写一份简洁的内容沉淀，使用清楚的中文，保留核心观点、重要事实和有价值的例子。不要营销化，不要添加原文没有的信息。输出严格 JSON：{"simple":"..."}。'''


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
    saved = store.get_setting('audio-skill-' + name, '').strip()
    if not saved:
        return DEFAULT_SKILLS[name]
    if name == 'clean' and saved == _LEGACY_CLEAN_SKILL:
        return DEFAULT_SKILLS[name]
    if name == 'simple' and saved == _LEGACY_SIMPLE_SKILL:
        return DEFAULT_SKILLS[name]
    if name == 'article' and saved.startswith('---\nname: interview-transcript-editor'):
        return DEFAULT_SKILLS[name]
    return saved


def _skill_customized(name: str) -> bool:
    saved = store.get_setting('audio-skill-' + name, '').strip()
    return bool(saved and saved == _skill(name))


def _feishu_user_configured() -> bool:
    return bool(
        os.environ.get('FEISHU_USER_ACCESS_TOKEN', '').strip()
        or os.environ.get('FEISHU_USER_REFRESH_TOKEN', '').strip()
        or store.get_setting('feishu-user-refresh-token', '').strip()
    )


def _feishu_app_configured() -> bool:
    return bool(
        os.environ.get('FEISHU_APP_ID', '').strip()
        and os.environ.get('FEISHU_APP_SECRET', '').strip()
    )


async def _feishu_user_token(client: httpx.AsyncClient) -> str:
    direct = os.environ.get('FEISHU_USER_ACCESS_TOKEN', '').strip()
    refresh_token = store.get_setting('feishu-user-refresh-token', '').strip() or os.environ.get('FEISHU_USER_REFRESH_TOKEN', '').strip()
    app_id = os.environ.get('FEISHU_APP_ID', '').strip()
    app_secret = os.environ.get('FEISHU_APP_SECRET', '').strip()
    if not refresh_token:
        if direct:
            return direct
        raise HTTPException(503, '尚未配置飞书用户授权。需要用户 access token，或 App ID、Secret 与用户 refresh token。')
    if not app_id or not app_secret:
        if direct:
            return direct
        raise HTTPException(503, '飞书用户 refresh token 已配置，但还缺少 App ID 或 App Secret。')
    api_base = os.environ.get('FEISHU_API_BASE', 'https://open.feishu.cn/open-apis').rstrip('/')
    try:
        response = await client.post(api_base + '/authen/v2/oauth/token', json={
            'grant_type': 'refresh_token',
            'client_id': app_id,
            'client_secret': app_secret,
            'refresh_token': refresh_token,
        })
        payload = _ensure_feishu_success(response, '飞书用户授权刷新失败') or {}
        token = str(payload.get('access_token') or (payload.get('data') or {}).get('access_token') or '')
        renewed = str(payload.get('refresh_token') or (payload.get('data') or {}).get('refresh_token') or '')
        if not token:
            raise ValueError('飞书没有返回用户 access token')
        if renewed and renewed != refresh_token:
            store.set_setting('feishu-user-refresh-token', renewed)
        return token
    except Exception:
        if direct:
            return direct
        raise


def _feishu_response_error(response: httpx.Response, fallback: str) -> str:
    """Keep Feishu's business error instead of reducing it to a bare HTTP 403."""
    code = None
    message = ''
    try:
        payload = response.json()
        code = payload.get('code')
        message = str(payload.get('msg') or payload.get('message') or '').strip()
    except Exception:
        message = response.text.strip()[:240]
    if not message:
        message = fallback
    suffix = f'（飞书错误码 {code}）' if code not in (None, 0) else ''
    return f'{message}{suffix}'


def _ensure_feishu_success(response: httpx.Response, fallback: str) -> dict | None:
    if not response.is_success:
        raise ValueError(_feishu_response_error(response, fallback))
    if 'json' not in response.headers.get('content-type', '').lower():
        return None
    payload = response.json()
    if payload.get('code') not in (None, 0):
        raise ValueError(_feishu_response_error(response, fallback))
    return payload


def _public_feishu_minute_sync(url: str) -> dict:
    """Read only a publicly shared Minutes page; no saved browser session is used."""
    from playwright.sync_api import sync_playwright

    timeout_ms = int(os.environ.get('FEISHU_PUBLIC_TIMEOUT_MS', '60000'))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage'],
        )
        context = browser.new_context(ignore_https_errors=False, locale='zh-CN')
        page = context.new_page()
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms)
            page.wait_for_function(
                """() => {
                    const text = document.body?.innerText || '';
                    return text.length >= 120 && /(^|\\s)\\d{1,2}:\\d{2}(\\s|$)/m.test(text);
                }""",
                timeout=timeout_ms,
            )
            text = page.locator('body').inner_text(timeout=timeout_ms).strip()
            title = page.title().strip()
        finally:
            context.close()
            browser.close()
    compact = re.sub(r'\s+', '', text)
    blocked_markers = ('登录飞书', '扫码登录', '无权限访问', '申请访问权限')
    if len(compact) < 120 or any(marker in text for marker in blocked_markers):
        raise ValueError('该妙记没有开启互联网用户可阅读，或公开页没有返回逐字稿')
    return {'title': title, 'transcript': text, 'source_kind': 'feishu', 'needs_ai': False}


async def _public_feishu_minute(url: str) -> dict:
    return await asyncio.to_thread(_public_feishu_minute_sync, url)


async def _feishu_minute_transcript(url: str) -> dict:
    match = _FEISHU_MINUTE.search(url)
    if not match:
        raise ValueError('妙记链接中没有识别到 minute token')
    api_base = os.environ.get('FEISHU_API_BASE', 'https://open.feishu.cn/open-apis').rstrip('/')
    minute_token = match.group(1)
    async with httpx.AsyncClient(timeout=60) as client:
        if not _feishu_user_configured():
            raise HTTPException(
                503,
                '这份妙记不能公开读取，服务器也没有飞书用户授权。'
                '妙记读取不会使用机器人身份；请配置 FEISHU_USER_REFRESH_TOKEN。',
            )
        try:
            token = await _feishu_user_token(client)
            headers = {'Authorization': 'Bearer ' + token}
            info_response = await client.get(api_base + f'/minutes/v1/minutes/{minute_token}', headers=headers)
            info = _ensure_feishu_success(info_response, '妙记信息读取失败') or {}
            minute = ((info.get('data') or {}).get('minute') or {})
            transcript_response = await client.get(
                api_base + f'/minutes/v1/minutes/{minute_token}/transcript',
                headers=headers,
                params={'need_speaker': 'true', 'need_timestamp': 'true', 'file_format': 'txt'},
            )
            transcript_payload = _ensure_feishu_success(transcript_response, '妙记逐字稿导出失败')
            transcript = transcript_response.text.strip()
            if transcript_payload is not None:
                data = transcript_payload.get('data') or {}
                transcript = str(data.get('transcript') or data.get('content') or '').strip()
            if not transcript:
                raise ValueError('妙记没有返回逐字稿')
            # This is the untouched source tier. It deliberately retains the
            # timestamps and speaker labels returned by Feishu.
            return {'title': str(minute.get('title') or ''), 'transcript': transcript, 'source_kind': 'feishu', 'needs_ai': False}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                422,
                f'飞书用户身份无法读取这份妙记：{str(exc)[:500]}。'
                '请检查你的妙记访问范围与逐字稿导出权限。',
            ) from exc


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
    result: list[str] = []
    timestamp = ''
    cue_lines: list[str] = []

    def flush() -> None:
        nonlocal cue_lines
        text = ' '.join(cue_lines).strip()
        cue_lines = []
        if not text:
            return
        value = f'[{timestamp}] {text}' if timestamp else text
        if not result or result[-1] != value:
            result.append(value)

    for line in raw.splitlines() + ['']:
        value = line.strip()
        if not value:
            flush()
            timestamp = ''
            continue
        match = re.match(r'(?P<start>\d{1,2}:\d{2}(?::\d{2})?)[.,]\d{3}\s+-->', value)
        if match:
            flush()
            timestamp = match.group('start')
            continue
        if value == 'WEBVTT' or value.startswith(('NOTE', 'Kind:', 'Language:')) or re.fullmatch(r'\d+', value):
            continue
        cleaned = re.sub(r'<[^>]+>', '', value).strip()
        if cleaned and (not cue_lines or cue_lines[-1] != cleaned):
            cue_lines.append(cleaned)
    return '\n'.join(result)


def _timestamp(seconds: object) -> str:
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return ''
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f'{hours:02d}:{minutes:02d}:{secs:02d}' if hours else f'{minutes:02d}:{secs:02d}'


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
            lines = []
            for item in body:
                content = str(item.get('content') or '').strip()
                if not content:
                    continue
                start = _timestamp(item.get('from'))
                lines.append(f'[{start}] {content}' if start else content)
            text = '\n'.join(lines)
            if not text: raise ValueError('字幕内容为空')
            return {'title': str(data.get('title') or ''), 'transcript': text, 'source_kind': 'bilibili', 'needs_ai': False}
    except Exception:
        # This fallback still uses --skip-download and only requests subtitle files.
        return _video_transcript(url)


async def _audio_model(model: str, purpose: str) -> None:
    try: options = await model_options()
    except ValueError as exc: raise HTTPException(503, str(exc))
    selected = next((item for item in options if item['id'] == model), None)
    if not selected: raise HTTPException(422, '请选择已经配置的模型')
    tasks = selected.get('tasks')
    if tasks and purpose not in tasks:
        label = '文本解析、清洗和纠错' if purpose == 'processing' else '稿件生成'
        raise HTTPException(422, f'这个模型不用于{label}，请重新选择')


async def _chat(model: str, system: str, text: str, purpose: str = 'article') -> dict:
    await _audio_model(model, purpose)
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
        'feishu_app_configured': _feishu_app_configured(),
        'feishu_user_configured': _feishu_user_configured(),
        'skills_configured': all(_skill_customized(name) for name in DEFAULT_SKILLS),
        'youtube_ready': bool(_executable('yt-dlp', 'YTDLP_BIN')),
        'xiaoyuzhou_ready': bool(_executable('xyz', 'XYZ_BIN') or _executable('xiaoyuzhou', 'XYZ_BIN')),
        'feishu_export_folder': os.environ.get('FEISHU_EXPORT_FOLDER_NAME', '沟通记录').strip() or '沟通记录',
    }


@router.put('/skills')
def save_skills(body: SkillInput):
    for name in DEFAULT_SKILLS: store.set_setting('audio-skill-' + name, getattr(body, name).strip())
    return {'ok': True}


@router.get('/projects')
def projects(): return {'projects': store.projects()}


@router.post('/projects')
def create_project(body: ProjectInput):
    data = body.model_dump()
    try: return store.save_project(data)
    except ValueError as exc: raise HTTPException(409, str(exc))


@router.put('/projects/{record_id}')
def update_project(record_id: str, body: ProjectInput):
    data = body.model_dump()
    try: return store.save_project(data, record_id)
    except ValueError as exc: raise HTTPException(409, str(exc))


@router.post('/import-url')
async def import_link(body: UrlInput):
    url = body.url.strip()
    is_feishu = any(x in url.lower() for x in ('feishu.cn', 'larksuite.com'))
    try:
        if is_feishu and _FEISHU_MINUTE.search(url):
            public_error = ''
            try:
                return await _public_feishu_minute(url)
            except Exception as exc:
                public_error = str(exc)[:240]
            try:
                return await _feishu_minute_transcript(url)
            except HTTPException as exc:
                raise HTTPException(exc.status_code, f'{exc.detail}（公开读取：{public_error}）') from exc
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
            raise HTTPException(422, '飞书应用没有读取到这份内容。请确认机器人有访问权限，或导出文字后粘贴/上传。') from exc
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
        title, text = parse_word_text(raw, name)
        return {'title': title, 'transcript': text, 'source_kind': 'file', 'needs_ai': False}
    if ext not in _AUDIO_EXT: raise HTTPException(422, '支持音频、视频、TXT、Markdown、SRT、VTT、DOC 和 DOCX')
    if not model: return {'title': Path(name).stem, 'transcript': '', 'source_kind': 'audio', 'needs_ai': True, 'notice': '需要使用 AI 识别。选择模型后再次点击开始识别。'}
    await _audio_model(model, 'processing')
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
    cleaned = await _chat(body.model, _skill('clean'), source, 'processing')
    clean_text = str(cleaned.get('cleaned', '')).strip()
    if not clean_text: raise HTTPException(502, '清洗结果不完整，原始文字仍然保留。')
    simple_source = f"标题：{body.title}\n\n原始逐字稿（用于恢复时间轴和细节）：\n{body.transcript}\n\n中文可读版（事实底稿）：\n{clean_text}"
    simple = await _chat(body.model, _skill('simple'), simple_source, 'processing')
    return {'cleaned': clean_text, 'simple': str(simple.get('simple', '')).strip(), 'uncertain': cleaned.get('uncertain', [])}


@router.post('/correct')
async def correct(body: CorrectionInput):
    system = '''你是逐字稿纠错器。严格按照用户的自然语言指令，检查清洗版和简版中的同类识别错误并同步修正。原版不在本次纠错范围内。只修改指令明确要求修正的词、人名、公司名、产品名或术语；保持其余文字、段落、说话人、标点和 [[?不确定片段?]] 标记不变，不润色、不删减、不总结。输出严格 JSON，不要 Markdown 代码围栏：{"cleaned":"修正后的清洗版","simple":"修正后的简版"}。'''
    source = f"纠错指令：{body.instruction}\n\n清洗版：\n{body.cleaned}\n\n简版：\n{body.simple}"
    result = await _chat(body.model, system, source, 'processing')
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
            folder_name = os.environ.get('FEISHU_EXPORT_FOLDER_NAME', '沟通记录').strip() or '沟通记录'
            folder_token = os.environ.get('FEISHU_EXPORT_FOLDER_TOKEN', '').strip()
            if not folder_token:
                list_response = await client.get(
                    api_base + '/drive/v1/files',
                    headers=headers,
                    params={'folder_token': '', 'page_size': 200},
                )
                list_payload = _ensure_feishu_success(list_response, '读取云盘文件夹失败') or {}
                matches = [
                    item for item in ((list_payload.get('data') or {}).get('files') or [])
                    if str(item.get('type') or '').lower() == 'folder'
                    and str(item.get('name') or '').strip() == folder_name
                    and str(item.get('token') or '').strip()
                ]
                if not matches:
                    raise ValueError(
                        f'没有在你的飞书云盘根目录找到“{folder_name}”文件夹。'
                        '请确认用户授权包含云盘读取权限，或在服务器 env 填写 FEISHU_EXPORT_FOLDER_TOKEN'
                    )
                if len(matches) > 1:
                    raise ValueError(
                        f'你的飞书云盘根目录有多个“{folder_name}”文件夹。'
                        '请在服务器 env 填写 FEISHU_EXPORT_FOLDER_TOKEN，避免导出到错误位置'
                    )
                folder_token = str(matches[0]['token']).strip()
            document_response = await client.post(
                api_base + '/docx/v1/documents',
                headers=headers,
                json={'title': body.title or '音频整理', 'folder_token': folder_token},
            )
            document_payload = _ensure_feishu_success(document_response, '创建文档失败') or {}
            document = ((document_payload.get('data') or {}).get('document') or {})
            document_id = str(document.get('document_id') or '')
            if not document_id: raise ValueError('飞书没有返回文档 ID')
            chunks: list[str] = []
            for paragraph in body.content.splitlines():
                if not paragraph.strip(): continue
                chunks.extend(paragraph[index:index + 1500] for index in range(0, len(paragraph), 1500))
            children = [{'block_type': 2, 'text': {'elements': [{'text_run': {'content': chunk}}]}} for chunk in chunks]
            for index in range(0, len(children), 50):
                block_response = await client.post(api_base + f'/docx/v1/documents/{document_id}/blocks/{document_id}/children', headers=headers, json={'children': children[index:index + 50]})
                _ensure_feishu_success(block_response, '写入文档正文失败')
        origin = os.environ.get('FEISHU_DOC_ORIGIN', 'https://geek.feishu.cn/docx').rstrip('/')
        return {'url': origin + '/' + document_id, 'document_id': document_id, 'folder_name': folder_name}
    except HTTPException: raise
    except Exception as exc:
        raise HTTPException(502, f'飞书文档创建失败：{str(exc)[:320]}。请检查用户授权、云盘读取权限与 docx:document 权限。') from exc


@router.post('/article')
async def article(body: ArticleInput):
    source = f"素材标题：{body.title}\n\n中文可读版（事实底稿）：\n{body.transcript}"
    if body.simple.strip():
        source += f"\n\n个人使用版（时间线与报道细节资料库）：\n{body.simple}"
    result = await _chat(body.model, _skill('article'), source)
    if not all(str(result.get(key, '')).strip() for key in ('title', 'body')):
        raise HTTPException(502, '稿件结果不完整，已有文字未改变。')
    return {key: str(result.get(key, '')).strip() for key in ('title', 'summary', 'body')}
