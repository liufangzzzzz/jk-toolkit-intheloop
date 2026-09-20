"""微信公众号草稿上传编排（uploadimg + 封面 + draft/add）。"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .client import WeChatApiClient
from .config import WeChatConfig, load_wechat_config
from .content import (
    collect_registry_image_bytes,
    fetch_image_bytes_from_url,
    parse_data_url,
    rewrite_html_image_src,
    truncate_wechat_fields,
)
from .image_upload import (
    MATERIAL_MAX_BYTES,
    UPLOADIMG_MAX_BYTES,
    PreparedWechatImage,
    prepare_body_image,
    prepare_cover_image,
)
from ..feishu.image_normalize import (
    normalize_feishu_image_for_wechat,
    parse_feishu_data_url_any_image,
)
from ..feishu.image_resolver import fetch_feishu_image_bytes_from_token
from ..feishu.public_image_store import fetch_public_image, is_public_image_ref

logger = logging.getLogger(__name__)

_IMG_SRC_RE = re.compile(r'\bsrc=["\']([^"\']+)["\']', re.IGNORECASE)
_PM_TRAILING_BREAK_P_RE = re.compile(
    r"<p[^>]*>\s*<span[^>]*>\s*<br[^>]*ProseMirror-trailingBreak[^>]*>\s*</span>\s*</p>",
    re.IGNORECASE,
)
_LEADING_EMPTY_P_AFTER_WRAP_RE = re.compile(
    r'(<(?:section|div)[^>]*class="[^"]*wx-article-wrap[^"]*"[^>]*>)\s*'
    r'(?:<p[^>]*>\s*(?:<span[^>]*>\s*)?<br[^>]*>\s*(?:</span>\s*)?</p>\s*)+',
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class WechatUploadModuleFailure:
    """单张图片/封面模块上传失败（不阻断整稿草稿创建）。"""

    module: str
    message: str
    block_id: str = ""


@dataclass
class WechatDraftResult:
    media_id: str
    failures: List[WechatUploadModuleFailure] = field(default_factory=list)
    image_url_mapping: Dict[str, str] = field(default_factory=dict)


class WeChatDraftService:
    def __init__(
        self,
        config: Optional[WeChatConfig] = None,
        *,
        account_id: Optional[str] = None,
    ) -> None:
        if config is not None:
            self._config = config
        else:
            if account_id:
                self._config = load_wechat_config(account_id)
            else:
                raise ValueError("WeChatDraftService 需要 config 或 account_id")
        self._client = WeChatApiClient(self._config)

    @property
    def config(self) -> WeChatConfig:
        return self._config

    def _resolve_image_bytes(
        self,
        src: str,
        *,
        is_feishu: bool,
    ) -> Optional[Tuple[bytes, str, str]]:
        """解析图片字节：(data, filename_hint, mime_hint)。"""
        mime_hint = ""
        public_image = fetch_public_image(src) if is_public_image_ref(src) else None
        parsed = parse_data_url(src) if not public_image else None
        if public_image:
            data, fname, mime_hint = public_image
        elif parsed:
            data, fname = parsed
        else:
            remote = fetch_image_bytes_from_url(src)
            if remote:
                data, fname = remote
            elif is_feishu or (src or "").strip().startswith("feishu-image://"):
                token_image = fetch_feishu_image_bytes_from_token(src)
                if token_image:
                    data, fname = token_image
                    mime_hint = ""
                else:
                    fallback = parse_feishu_data_url_any_image(src)
                    if not fallback:
                        return None
                    data, fname, mime_hint = fallback
            else:
                return None
        if is_feishu or (src or "").strip().startswith("feishu-image://"):
            data, fname, mime_hint = normalize_feishu_image_for_wechat(
                data, fname, mime_hint=mime_hint
            )
        return data, fname, mime_hint

    def _log_image_audit(
        self,
        *,
        role: str,
        block_id: str,
        fname: str,
        raw_len: int,
        prepared: PreparedWechatImage,
    ) -> None:
        over_body = raw_len > UPLOADIMG_MAX_BYTES
        over_material = raw_len > MATERIAL_MAX_BYTES
        logger.info(
            "图片上传前审核 role=%s block=%s file=%s raw_bytes=%s over_uploadimg=%s "
            "over_material=%s prepared_bytes=%s via=%s normalized=%s",
            role,
            block_id or "-",
            fname,
            raw_len,
            over_body,
            over_material,
            prepared.prepared_bytes,
            prepared.upload_via,
            prepared.normalized,
        )

    def _upload_prepared_body(self, prepared: PreparedWechatImage) -> str:
        if prepared.upload_via == "material":
            return self._client.add_material_image_url(
                prepared.data, prepared.filename
            )
        return self._client.uploadimg(prepared.data, prepared.filename)

    def create_draft_from_html(
        self,
        *,
        title: str,
        author: str,
        digest: str,
        html: str,
        figure_registry: List[Dict[str, Any]],
        source_channel: str = "word",
        skip_cover: bool = False,
    ) -> WechatDraftResult:
        """
        将排版 HTML 与 figure_registry 上传为微信草稿。

        1. 全部图片（正文 + 头图封面）上传前经 prepare_* 清洗
        2. 正文图：uploadimg / add_material(url)；单张失败记入 failures，不阻断草稿
        3. 封面：add_material → thumb_media_id；失败时尝试默认封面或正文首图（不抛错阻断）
        4. skip_cover=True（早知道）：不上传独立头图模块，仅用预设 thumb 或正文首图作草稿封面
        5. draft/add
        """
        self._config.require_credentials()
        registry_images = collect_registry_image_bytes(figure_registry)
        is_feishu = str(source_channel or "").strip().lower() == "feishu"
        failures: List[WechatUploadModuleFailure] = []

        registry_srcs: List[str] = []
        for ent in figure_registry or []:
            src = str(ent.get("image_url") or "")
            if not src or src in registry_srcs:
                continue
            registry_srcs.append(src)
        html_extra: List[str] = []
        for src in _IMG_SRC_RE.findall(html or ""):
            if src in registry_srcs or src in html_extra or src.startswith("https://mmbiz."):
                continue
            if src.startswith("data:image") or src.startswith(("http://", "https://")):
                html_extra.append(src)
        total = len(registry_srcs) + len(html_extra)
        logger.info(
            "开始上传正文图片（含上传前清洗）",
            extra={
                "account_label": self._config.account_label,
                "image_count": total,
                "registry_count": len(registry_srcs),
            },
        )

        url_map: Dict[str, str] = {}
        step = 0

        def _record_failure(
            *,
            module: str,
            block_id: str,
            message: str,
            src: str = "",
        ) -> None:
            msg = message[:300]
            failures.append(
                WechatUploadModuleFailure(
                    module=module,
                    block_id=block_id,
                    message=msg,
                )
            )
            logger.warning(
                "微信图片模块上传失败（将继续创建草稿） module=%s block=%s src=%s err=%s",
                module,
                block_id or "-",
                (src[:64] + "…") if len(src) > 64 else (src or "-"),
                msg[:120],
            )

        # 收集全部待上传图片的信息（先不处理）
        _image_tasks: list[dict] = []
        _img_seq = 0
        for ent in figure_registry or []:
            src = str(ent.get("image_url") or "")
            if not src:
                continue
            _img_seq += 1
            _image_tasks.append({
                "src": src,
                "block_id": str(ent.get("block_id") or ""),
                "module_label": str(ent.get("label_zh") or "正文图片"),
                "seq": _img_seq,
            })
        for src in html_extra:
            _img_seq += 1
            _image_tasks.append({
                "src": src,
                "block_id": "",
                "module_label": "正文(HTML兜底)",
                "seq": _img_seq,
            })

        # Phase 1：并行 resolve + prepare（PIL 压缩 CPU 密集，用线程池加速）
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading

        _prep_lock = threading.Lock()
        _prepared: Dict[str, tuple] = {}  # src → (PreparedWechatImage, raw_len, fname) or None (failed)
        _prep_failures: list[dict] = []

        def _resolve_and_prepare(task: dict) -> None:
            src = task["src"]
            block_id = task["block_id"]
            module_label = task["module_label"]
            seq = task.get("seq", 0)
            seq_label = f"第{seq}张图片" if seq else "图片"
            resolved = self._resolve_image_bytes(src, is_feishu=is_feishu)
            if not resolved:
                with _prep_lock:
                    _prep_failures.append({
                        "module": module_label,
                        "block_id": block_id,
                        "message": (
                            f"{seq_label}（{module_label}）无法解析，"
                            f"可能是 Word 内嵌的特殊格式图片，请到公众号后台手动上传此图"
                        ),
                        "src": src,
                    })
                _prepared[src] = None
                return
            data, fname, mime_hint = resolved
            raw_len = len(data)
            try:
                prepared = prepare_body_image(data, fname, mime_hint=mime_hint)
            except Exception as exc:
                with _prep_lock:
                    _prep_failures.append({
                        "module": module_label,
                        "block_id": block_id,
                        "message": (
                            f"{seq_label}（{module_label}）格式不支持（{exc}），"
                            f"请替换为 PNG/JPG 后重新上传，或到公众号后台手动上传"
                        )[:300],
                        "src": src,
                    })
                _prepared[src] = None
                return
            with _prep_lock:
                _prepared[src] = (prepared, raw_len, fname, block_id, module_label)

        max_workers = min(len(_image_tasks), 6) if _image_tasks else 1
        if _image_tasks:
            logger.info(
                "并行预处理图片 phase=resolve+prepare count=%d workers=%d",
                len(_image_tasks),
                max_workers,
            )
            t_prep_start = time.monotonic()
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_task = {
                    executor.submit(_resolve_and_prepare, t): t for t in _image_tasks
                }
                for f in as_completed(future_to_task):
                    task_info = future_to_task[f]
                    try:
                        f.result(timeout=15)  # 单张图片处理超时 15s，确保总上传 ≤1 分钟
                    except Exception as exc:
                        src = task_info["src"]
                        seq = task_info.get("seq", 0)
                        seq_label = f"第{seq}张图片" if seq else "图片"
                        err_msg = (
                            f"{seq_label}（{task_info['module_label']}）处理超时或格式不支持，"
                            f"请到公众号后台手动上传此图"
                        )
                        logger.warning(
                            "%s src=%s err=%s",
                            err_msg,
                            src[:80],
                            exc,
                        )
                        with _prep_lock:
                            _prepared[src] = None
                            _prep_failures.append({
                                "module": task_info["module_label"],
                                "block_id": task_info["block_id"],
                                "message": err_msg[:300],
                                "src": src,
                            })
            logger.info(
                "并行预处理完成 elapsed_s=%.1f count=%d",
                time.monotonic() - t_prep_start,
                len(_image_tasks),
            )

        # Phase 2：串行上传（WeChat API 客户端非线程安全，顺序调用）
        for task in _image_tasks:
            src = task["src"]
            block_id = task["block_id"]
            module_label = task["module_label"]
            if src in url_map:
                continue
            entry = _prepared.get(src)
            if entry is None:
                # 预处理失败，记录并继续
                for pf in _prep_failures:
                    if pf["src"] == src:
                        _record_failure(
                            module=pf["module"],
                            block_id=pf["block_id"],
                            message=pf["message"],
                            src=pf["src"],
                        )
                        break
                continue
            prepared, raw_len, fname, _bid, _ml = entry
            self._log_image_audit(
                role=module_label,
                block_id=block_id,
                fname=fname,
                raw_len=raw_len,
                prepared=prepared,
            )
            step += 1
            t0 = time.monotonic()
            logger.info(
                "上传正文图 %s/%s block=%s %s raw=%s prepared=%s",
                step,
                total,
                block_id or "-",
                prepared.filename,
                raw_len,
                prepared.prepared_bytes,
            )
            try:
                url_map[src] = self._upload_prepared_body(prepared)
            except Exception as exc:
                seq = task.get("seq", 0)
                seq_label = f"第{seq}张图片" if seq else "图片"
                _record_failure(
                    module=module_label,
                    block_id=block_id,
                    message=(
                        f"{seq_label}（{module_label}）上传微信失败，"
                        f"请到公众号后台手动上传此图"
                    ),
                    src=src,
                )
                continue
            logger.info(
                "正文图 %s/%s 完成 elapsed_s=%.1f via=%s",
                step,
                total,
                time.monotonic() - t0,
                prepared.upload_via,
            )

        content = rewrite_html_image_src(
            sanitize_wechat_upload_html(html),
            url_map,
        )

        thumb_media_id = (self._config.thumb_media_id or "").strip()
        if not thumb_media_id and not skip_cover:
            thumb_media_id, cover_failures = self._upload_cover_thumb_resilient(
                figure_registry=figure_registry,
                registry_images=registry_images,
                is_feishu=is_feishu,
                html=html,
            )
            failures.extend(cover_failures)
        elif not thumb_media_id and skip_cover:
            thumb_media_id, thumb_failures = self._thumb_from_first_html_image(
                html, is_feishu=is_feishu
            )
            failures.extend(thumb_failures)

        if not thumb_media_id:
            failures.append(
                WechatUploadModuleFailure(
                    module="封面",
                    message="未获取草稿封面 thumb_media_id（已跳过独立头图上传）",
                )
            )
            logger.warning(
                "草稿缺少 thumb_media_id，仍将尝试 draft_add",
                extra={"account_label": self._config.account_label, "skip_cover": skip_cover},
            )

        t, a, d, c = truncate_wechat_fields(title, author, digest, content)
        article: Dict[str, Any] = {
            "article_type": "news",
            "title": t,
            "author": a,
            "digest": d,
            "content": c,
            "need_open_comment": 1,          # 默认开启留言
            "only_fans_can_comment": 0,      # 所有人可评论
        }
        if thumb_media_id:
            article["thumb_media_id"] = thumb_media_id

        media_id = self._client.draft_add([article])
        logger.info(
            "微信草稿已创建",
            extra={
                "account_label": self._config.account_label,
                "media_id": media_id[:16] + "…" if len(media_id) > 16 else media_id,
                "upload_failures": len(failures),
            },
        )
        if failures:
            logger.warning(
                "微信草稿已创建但存在 %s 个图片模块上传失败",
                len(failures),
                extra={"modules": [f.module for f in failures]},
            )
        return WechatDraftResult(
            media_id=media_id,
            failures=failures,
            image_url_mapping=url_map,
        )

    def _thumb_from_first_html_image(
        self,
        html: str,
        *,
        is_feishu: bool,
    ) -> Tuple[str, List[WechatUploadModuleFailure]]:
        """从正文 HTML 取第一张图作为草稿封面（早知道等无独立头图场景）。"""
        failures: List[WechatUploadModuleFailure] = []
        for src in _IMG_SRC_RE.findall(html or ""):
            src = src.strip()
            if not src:
                continue
            resolved = self._resolve_image_bytes(src, is_feishu=is_feishu)
            if not resolved:
                failures.append(
                    WechatUploadModuleFailure(
                        module="封面(正文首图)",
                        message="无法解析正文首图",
                    )
                )
                continue
            data, fname, mime_hint = resolved
            try:
                prepared = prepare_cover_image(data, fname, mime_hint=mime_hint)
                thumb = self._client.add_material_image(prepared.data, prepared.filename)
                logger.info("已用正文首图作为草稿封面")
                return thumb, failures
            except Exception as exc:
                failures.append(
                    WechatUploadModuleFailure(
                        module="封面(正文首图)",
                        message=str(exc)[:300],
                    )
                )
        if not failures:
            failures.append(
                WechatUploadModuleFailure(
                    module="封面(正文首图)",
                    message="正文中未找到可上传为封面的图片",
                )
            )
        return "", failures

    def _upload_cover_thumb_resilient(
        self,
        *,
        figure_registry: List[Dict[str, Any]],
        registry_images: list,
        is_feishu: bool,
        html: str = "",
    ) -> Tuple[str, List[WechatUploadModuleFailure]]:
        """上传封面；失败时尝试默认封面 / 正文首图，不抛错阻断草稿。"""
        failures: List[WechatUploadModuleFailure] = []
        cover_ent = registry_cover_entry(figure_registry or [])
        module_label = (
            str(cover_ent.get("label_zh") or "封面") if cover_ent else "封面"
        )
        block_id = str(cover_ent.get("block_id") or "") if cover_ent else ""

        try:
            return (
                self._upload_cover_thumb(
                    figure_registry=figure_registry,
                    registry_images=registry_images,
                    is_feishu=is_feishu,
                ),
                failures,
            )
        except Exception as exc:
            failures.append(
                WechatUploadModuleFailure(
                    module=module_label,
                    block_id=block_id,
                    message=str(exc)[:300],
                )
            )
            logger.warning(
                "头图封面上传失败，尝试默认封面",
                extra={"block_id": block_id or "-", "error": str(exc)[:200]},
            )

        try:
            cover_bytes, cover_fname = self._client.load_cover_bytes(registry_images)
            prepared = prepare_cover_image(cover_bytes, cover_fname)
            thumb = self._client.add_material_image(prepared.data, prepared.filename)
            logger.info("已使用备用封面创建草稿")
            return thumb, failures
        except Exception as exc2:
            failures.append(
                WechatUploadModuleFailure(
                    module="封面",
                    block_id=block_id,
                    message=f"头图与备用封面均上传失败: {exc2}"[:300],
                )
            )

        thumb, html_failures = self._thumb_from_first_html_image(html, is_feishu=is_feishu)
        failures.extend(html_failures)
        if thumb:
            logger.info("头图失败后已改用正文首图作为封面")
            return thumb, failures
        return "", failures

    def _upload_cover_thumb(
        self,
        *,
        figure_registry: List[Dict[str, Any]],
        registry_images: list,
        is_feishu: bool,
    ) -> str:
        cover_ent = registry_cover_entry(figure_registry or [])
        cover_bytes: Optional[bytes] = None
        cover_fname = "cover.jpg"
        mime_hint = ""
        block_id = ""

        if cover_ent:
            block_id = str(cover_ent.get("block_id") or "")
            src = str(cover_ent.get("image_url") or "")
            resolved = self._resolve_image_bytes(src, is_feishu=is_feishu)
            if resolved:
                cover_bytes, cover_fname, mime_hint = resolved
            elif src:
                raise ValueError("无法解析头图数据")

        if cover_bytes is None and registry_images:
            _, cover_bytes, cover_fname = registry_images[0]

        if cover_bytes is None:
            cover_bytes, cover_fname = self._client.load_cover_bytes(registry_images)

        raw_len = len(cover_bytes)
        prepared = prepare_cover_image(cover_bytes, cover_fname, mime_hint=mime_hint)
        self._log_image_audit(
            role="封面",
            block_id=block_id,
            fname=cover_fname,
            raw_len=raw_len,
            prepared=prepared,
        )
        if raw_len > MATERIAL_MAX_BYTES:
            logger.warning(
                "头图原始体积超过微信永久素材上限，已清洗后上传",
                extra={
                    "raw_bytes": raw_len,
                    "prepared_bytes": prepared.prepared_bytes,
                    "limit": MATERIAL_MAX_BYTES,
                },
            )
        t0 = time.monotonic()
        thumb = self._client.add_material_image(prepared.data, prepared.filename)
        logger.info(
            "封面上传完成 elapsed_s=%.1f raw=%s prepared=%s via=material",
            time.monotonic() - t0,
            raw_len,
            prepared.prepared_bytes,
        )
        return thumb

    def _upload_body_image(
        self, data: bytes, filename_hint: str, *, mime_hint: str = ""
    ) -> str:
        prepared = prepare_body_image(data, filename_hint, mime_hint=mime_hint)
        return self._upload_prepared_body(prepared)


_draft_services: Dict[str, WeChatDraftService] = {}


def get_wechat_draft_service(account_id: str) -> WeChatDraftService:
    """按公众号账号 id 获取草稿服务（每账号独立 Client/token 缓存）。"""
    aid = (account_id or "").strip()
    if not aid:
        raise ValueError("wechat_account_id 不能为空")
    if aid not in _draft_services:
        _draft_services[aid] = WeChatDraftService(account_id=aid)
    return _draft_services[aid]


def registry_cover_entry(registry: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Select the first header image, falling back to the first registry item."""
    for entry in registry:
        if entry.get("is_header"):
            return entry
    return registry[0] if registry else None


def sanitize_wechat_upload_html(html_text: str) -> str:
    """Final InTheLoop-owned HTML cleanup before WeChat draft upload."""
    s = _PM_TRAILING_BREAK_P_RE.sub("", html_text or "")
    prev = None
    while prev != s:
        prev = s
        s = _LEADING_EMPTY_P_AFTER_WRAP_RE.sub(r"\1", s, count=1)
    return s
