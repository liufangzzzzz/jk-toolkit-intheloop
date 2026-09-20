"""飞书来源图片规范化（仅在 source_channel=feishu 时调用）。"""
from __future__ import annotations

import base64
import re
from typing import Optional, Tuple

from ..mime_sniff import sniff_image_mime_from_bytes

_DATA_URL_ANY_IMAGE_RE = re.compile(
    r"^data:(?P<mime>image/[^;,]+);base64,(?P<data>.+)$",
    re.IGNORECASE | re.DOTALL,
)


def parse_feishu_data_url_any_image(url: str) -> Optional[Tuple[bytes, str, str]]:
    """
    解析飞书 data URL（支持 png/jpg/gif/webp 等 image/*）。

    返回: (bytes, filename_hint, mime_hint)
    """
    m = _DATA_URL_ANY_IMAGE_RE.match((url or "").strip())
    if not m:
        return None
    mime = str(m.group("mime") or "").lower().strip()
    try:
        raw = base64.b64decode(m.group("data"), validate=False)
    except Exception:
        return None
    if not raw:
        return None
    ext = mime.split("/")[-1] or "jpg"
    if ext == "jpeg":
        ext = "jpg"
    return raw, f"image.{ext}", mime


def normalize_feishu_image_for_wechat(
    data: bytes, filename_hint: str, *, mime_hint: str = ""
) -> Tuple[bytes, str, str]:
    """
    飞书图片规范化：
    - 常见 png/jpg/gif/webp 直接透传（由 wechat.image_upload 决定上传通道）
    - 其他 image/* 尝试转 png，减少微信上传失败概率
    """
    sniffed = (sniff_image_mime_from_bytes(data) or "").lower().strip()
    mime = sniffed or (mime_hint or "").lower().strip()

    if mime in {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}:
        out_name = filename_hint or "image.jpg"
        if mime == "image/jpeg":
            out_name = "image.jpg"
        elif mime == "image/jpg":
            out_name = "image.jpg"
        elif mime == "image/png":
            out_name = "image.png"
        elif mime == "image/gif":
            out_name = "image.gif"
        elif mime == "image/webp":
            out_name = "image.webp"
        return data, out_name, mime

    try:
        from PIL import Image  # type: ignore[import-untyped]
        import io

        im = Image.open(io.BytesIO(data))
        if getattr(im, "n_frames", 1) > 1:
            im.seek(0)
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA")
        out = io.BytesIO()
        im.save(out, format="PNG", optimize=True)
        return out.getvalue(), "image.png", "image/png"
    except Exception:
        return data, (filename_hint or "image.jpg"), mime
