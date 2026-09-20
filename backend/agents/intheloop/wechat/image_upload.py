"""
微信图文图片上传前处理：正文与封面共用清洗管线。

与微信开放平台约定对齐：
- uploadimg（正文静图）：jpg/png，<1MB
- add_material image（封面 thumb / 正文 GIF）：≤10MB
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional, Tuple

from ..mime_sniff import sniff_image_mime_from_bytes

logger = logging.getLogger(__name__)

UPLOADIMG_MAX_BYTES = 1_048_576
UPLOADIMG_TARGET_BYTES = 921_600
MATERIAL_MAX_BYTES = 10_485_760
# 封面永久素材留余量，避免边界触发 45001
COVER_TARGET_BYTES = 9_500_000

UploadVia = Literal["uploadimg", "material"]
ImagePurpose = Literal["body", "cover"]


@dataclass(frozen=True)
class PreparedWechatImage:
    data: bytes
    filename: str
    upload_via: UploadVia
    original_bytes: int
    prepared_bytes: int
    normalized: bool
    purpose: ImagePurpose


# 兼容旧名
PreparedBodyImage = PreparedWechatImage


def mime_from_filename(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".png":
        return "image/png"
    if ext == ".gif":
        return "image/gif"
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".bmp":
        return "image/bmp"
    return "image/jpeg"


def _declared_gif(sniffed: Optional[str], filename: str, mime_hint: str = "") -> bool:
    if sniffed == "image/gif":
        return True
    if filename.lower().endswith(".gif"):
        return True
    if mime_hint and "gif" in mime_hint.lower():
        return True
    return False


def _is_animated(data: bytes) -> bool:
    try:
        from PIL import Image  # type: ignore[import-untyped]

        im = Image.open(io.BytesIO(data))
        return bool(getattr(im, "is_animated", False)) or int(getattr(im, "n_frames", 1)) > 1
    except Exception:
        return False


def _webp_to_gif_bytes(data: bytes) -> bytes:
    from PIL import Image  # type: ignore[import-untyped]

    im = Image.open(io.BytesIO(data))
    frames = []
    try:
        for frame_idx in range(im.n_frames):
            im.seek(frame_idx)
            frames.append(im.convert("RGBA"))
    except Exception:
        frames = [im.convert("RGBA")]

    out = io.BytesIO()
    if len(frames) == 1:
        frames[0].save(out, format="GIF", optimize=True)
    else:
        frames[0].save(
            out,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            loop=0,
            optimize=True,
            duration=im.info.get("duration", 100) or 100,
        )
    return out.getvalue()


def _shrink_gif_bytes(data: bytes, max_bytes: int) -> bytes:
    if len(data) <= max_bytes:
        return data
    from PIL import Image  # type: ignore[import-untyped]

    im = Image.open(io.BytesIO(data))
    n_frames = int(getattr(im, "n_frames", 1))
    scale = 0.85
    current = data
    for _ in range(8):
        if len(current) <= max_bytes:
            return current
        w, h = im.size
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        frames = []
        for i in range(n_frames):
            im.seek(i)
            frames.append(
                im.resize((nw, nh), Image.Resampling.LANCZOS).convert(
                    "P", palette=Image.Palette.ADAPTIVE
                )
            )
        out = io.BytesIO()
        if len(frames) == 1:
            frames[0].save(out, format="GIF", optimize=True)
        else:
            duration = im.info.get("duration", 100) or 100
            frames[0].save(
                out,
                format="GIF",
                save_all=True,
                append_images=frames[1:],
                loop=0,
                optimize=True,
                duration=duration,
            )
        current = out.getvalue()
        im = Image.open(io.BytesIO(current))
        scale *= 0.85
    if len(current) > max_bytes:
        raise ValueError(
            f"GIF 体积 {len(current)} 字节仍超过微信上限 {max_bytes}，请缩小源图后重试"
        )
    return current


def _compress_static_to_jpeg_or_png(
    data: bytes,
    *,
    target_bytes: int = UPLOADIMG_TARGET_BYTES,
) -> Tuple[bytes, str]:
    from PIL import Image, UnidentifiedImageError  # type: ignore[import-untyped]

    # 防守：空数据、极小数据直接跳过
    if not data or len(data) < 64:
        raise ValueError(f"图片数据异常（{len(data)} bytes），无法处理")

    sniffed = sniff_image_mime_from_bytes(data)
    # 防守：PIL 无法处理的格式（Word 常内嵌 EMF/WMF），提前拒绝
    _UNSUPPORTED_SNIFF = frozenset({"image/emf", "image/wmf", "image/x-emf", "image/x-wmf"})
    if sniffed and sniffed.lower() in _UNSUPPORTED_SNIFF:
        raise ValueError(
            f"Word 内嵌图片格式 {sniffed} 微信不支持，"
            f"请在 Word 中将其替换为 PNG/JPG 后重新上传"
        )

    if len(data) <= target_bytes and sniffed == "image/png":
        return data, "image.png"

    try:
        im = Image.open(io.BytesIO(data))
    except UnidentifiedImageError:
        raise ValueError(
            f"无法识别图片格式（{len(data)} bytes，sniff={sniffed}），"
            f"可能是 Word 内嵌的非标准图片，请替换为 PNG/JPG"
        ) from None
    if getattr(im, "n_frames", 1) > 1:
        im.seek(0)
    if im.mode in ("RGBA", "P"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        layer = im.convert("RGBA") if im.mode == "P" else im
        bg.paste(layer, mask=layer.split()[-1] if layer.mode == "RGBA" else None)
        im = bg
    elif im.mode != "RGB":
        im = im.convert("RGB")

    size_ratio = len(data) / max(target_bytes, 1)
    # 智能起点：按体积超出比例估算起步 quality
    if size_ratio > 10:
        quality = 45
    elif size_ratio > 5:
        quality = 65
    elif size_ratio > 2:
        quality = 80
    else:
        quality = 90

    while quality >= 40:
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=quality, optimize=True)
        buf = out.getvalue()
        if len(buf) <= target_bytes:
            return buf, "image.jpg"
        quality -= 10  # 步长 10 替代 8，减少迭代

    # 压缩不足 → 缩尺寸（单步到位，避免多轮试错）
    w, h = im.size
    target_ratio = (target_bytes / max(len(data), 1)) ** 0.4
    scale = max(0.3, min(0.85, target_ratio))
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    resized = im.resize((nw, nh), Image.Resampling.LANCZOS)
    for quality in (75, 60, 45):
        out = io.BytesIO()
        resized.save(out, format="JPEG", quality=quality, optimize=True)
        buf = out.getvalue()
        if len(buf) <= target_bytes:
            return buf, "image.jpg"

    out = io.BytesIO()
    resized.save(out, format="JPEG", quality=35, optimize=True)
    return out.getvalue(), "image.jpg"


def _needs_normalization(
    original_len: int,
    prepared_len: int,
    prepared_filename: str,
    filename_hint: str,
) -> bool:
    if original_len != prepared_len:
        return True
    orig_ext = Path(filename_hint or "").suffix.lower()
    prep_ext = Path(prepared_filename or "").suffix.lower()
    return orig_ext != prep_ext and prep_ext in (".jpg", ".jpeg", ".gif")


def _prepare_gif_material(data: bytes, max_bytes: int) -> Tuple[bytes, str]:
    gif_bytes = _shrink_gif_bytes(data, max_bytes)
    return gif_bytes, "image.gif"


def prepare_wechat_image(
    data: bytes,
    filename_hint: str = "image.jpg",
    *,
    mime_hint: str = "",
    purpose: ImagePurpose = "body",
) -> PreparedWechatImage:
    """
    上传前统一清洗：飞书/Word 全部图片均应经此函数后再调微信 API。

    - purpose=body：静图 → uploadimg（≤约 900KB）；GIF/动图 → add_material url
    - purpose=cover：头图 → add_material thumb（静图/GIF 均 ≤10MB，封面可用更高压缩上限）
    """
    if not data:
        raise ValueError("图片数据为空")

    original_len = len(data)
    sniffed = sniff_image_mime_from_bytes(data)
    fname = filename_hint or "image.jpg"
    max_material = MATERIAL_MAX_BYTES
    static_target = (
        COVER_TARGET_BYTES if purpose == "cover" else UPLOADIMG_TARGET_BYTES
    )

    if _declared_gif(sniffed, fname, mime_hint):
        out_data, out_name = _prepare_gif_material(data, max_material)
        upload_via: UploadVia = "material"
    elif sniffed == "image/webp" and _is_animated(data):
        gif_bytes = _webp_to_gif_bytes(data)
        out_data, out_name = _prepare_gif_material(gif_bytes, max_material)
        upload_via = "material"
    elif purpose == "body" and len(data) <= UPLOADIMG_MAX_BYTES and sniffed == "image/png":
        out_data, out_name = data, "image.png"
        upload_via = "uploadimg"
    elif (
        purpose == "body"
        and len(data) <= UPLOADIMG_TARGET_BYTES
        and sniffed in ("image/jpeg", "image/jpg", None)
    ):
        ext = ".jpg" if not fname.lower().endswith(".png") else Path(fname).suffix
        out_data = data
        out_name = f"image{ext if ext in ('.jpg', '.jpeg', '.png') else '.jpg'}"
        upload_via = "uploadimg"
    elif (
        purpose == "cover"
        and len(data) <= COVER_TARGET_BYTES
        and sniffed in ("image/jpeg", "image/jpg", "image/png")
    ):
        # 封面：体积已合规的静图可直传永久素材
        out_data = data
        out_name = fname if Path(fname).suffix else "image.jpg"
        upload_via = "material"
    else:
        out_data, out_name = _compress_static_to_jpeg_or_png(
            data, target_bytes=static_target
        )
        upload_via = "material" if purpose == "cover" else "uploadimg"

    prepared_len = len(out_data)
    normalized = _needs_normalization(original_len, prepared_len, out_name, fname)

    limit_label = (
        f"material≤{max_material}"
        if upload_via == "material" and purpose == "cover"
        else (
            f"material≤{max_material}"
            if upload_via == "material"
            else f"uploadimg≤{UPLOADIMG_MAX_BYTES}"
        )
    )
    if normalized or original_len > static_target:
        logger.info(
            "微信图片已清洗 purpose=%s via=%s %s→%s bytes %s→%s %s",
            purpose,
            upload_via,
            fname,
            out_name,
            original_len,
            prepared_len,
            limit_label,
        )
    elif original_len > UPLOADIMG_MAX_BYTES and purpose == "body":
        logger.info(
            "微信正文图已合规 purpose=body via=%s bytes=%s（未超 uploadimg 硬上限）",
            upload_via,
            prepared_len,
        )

    return PreparedWechatImage(
        data=out_data,
        filename=out_name,
        upload_via=upload_via,
        original_bytes=original_len,
        prepared_bytes=prepared_len,
        normalized=normalized,
        purpose=purpose,
    )


def prepare_body_image(
    data: bytes,
    filename_hint: str = "image.jpg",
    *,
    mime_hint: str = "",
) -> PreparedWechatImage:
    """正文内嵌图（兼容旧接口）。"""
    return prepare_wechat_image(
        data, filename_hint, mime_hint=mime_hint, purpose="body"
    )


def prepare_cover_image(
    data: bytes,
    filename_hint: str = "cover.jpg",
    *,
    mime_hint: str = "",
) -> PreparedWechatImage:
    """草稿封面（头图）→ add_material thumb，上限 10MB。"""
    return prepare_wechat_image(
        data, filename_hint, mime_hint=mime_hint, purpose="cover"
    )
