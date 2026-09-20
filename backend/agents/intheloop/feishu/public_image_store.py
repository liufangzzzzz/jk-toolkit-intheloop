"""Short-lived local image cache for public Feishu documents."""
from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path
from typing import Optional, Tuple

from ..mime_sniff import sniff_image_mime_from_bytes

_TOKEN_RE = re.compile(r"^[a-f0-9]{64}$")
_SCHEME = "public-image://"


def _cache_dir() -> Path:
    return Path(
        os.environ.get("ITL_PUBLIC_IMAGE_CACHE_DIR", "/tmp/intheloop-public-images")
    )


def _max_bytes() -> int:
    raw = os.environ.get("ITL_PUBLIC_IMAGE_MAX_BYTES", str(20 * 1024 * 1024))
    try:
        return max(1024, int(raw))
    except ValueError:
        return 20 * 1024 * 1024


def _ttl_seconds() -> int:
    raw = os.environ.get("ITL_PUBLIC_IMAGE_TTL_SECONDS", str(24 * 60 * 60))
    try:
        return max(300, int(raw))
    except ValueError:
        return 24 * 60 * 60


def _cleanup_expired(directory: Path) -> None:
    cutoff = time.time() - _ttl_seconds()
    try:
        for path in directory.glob("*.bin"):
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
    except OSError:
        # Cache cleanup is best effort and must not block parsing.
        return


def store_public_image(data: bytes) -> str:
    """Store an image and return a compact URL-like reference."""
    if not data:
        raise ValueError("图片内容为空")
    if len(data) > _max_bytes():
        raise ValueError("图片超过单图大小限制")
    mime = sniff_image_mime_from_bytes(data)
    if not mime or not mime.startswith("image/"):
        raise ValueError("资源不是可识别的图片")

    token = hashlib.sha256(data).hexdigest()
    directory = _cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    _cleanup_expired(directory)
    target = directory / f"{token}.bin"
    if not target.exists():
        temporary = directory / f".{token}.{os.getpid()}.tmp"
        temporary.write_bytes(data)
        temporary.replace(target)
    return f"{_SCHEME}{token}"


def fetch_public_image(ref: str) -> Optional[Tuple[bytes, str, str]]:
    """Resolve a public-image reference into bytes, filename and MIME type."""
    value = (ref or "").strip()
    token = value.removeprefix(_SCHEME) if value.startswith(_SCHEME) else value
    if not _TOKEN_RE.fullmatch(token):
        return None
    target = _cache_dir() / f"{token}.bin"
    try:
        data = target.read_bytes()
    except OSError:
        return None
    if target.stat().st_mtime < time.time() - _ttl_seconds():
        target.unlink(missing_ok=True)
        return None
    mime = sniff_image_mime_from_bytes(data) or "image/jpeg"
    ext = mime.split("/", 1)[-1].replace("jpeg", "jpg")
    return data, f"image.{ext}", mime


def is_public_image_ref(value: str) -> bool:
    return (value or "").strip().startswith(_SCHEME)
