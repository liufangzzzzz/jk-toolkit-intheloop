from __future__ import annotations

import mimetypes
import os
import re
import uuid
from pathlib import Path

_TOKEN_RE = re.compile(r"^[a-f0-9]{32}\.[a-z0-9]{1,8}$")
_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/tiff": ".tif",
}


def asset_root() -> Path:
    configured = os.environ.get("ITL_IMPORT_ASSET_PATH", "").strip()
    root = Path(configured) if configured else Path.cwd() / ".local-data" / "import-assets"
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_asset(raw: bytes, content_type: str, *, suffix: str = "") -> str:
    if not raw:
        raise ValueError("图片内容为空")
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    extension = _EXTENSIONS.get(normalized_type)
    if not extension and suffix:
        extension = Path(suffix).suffix.lower()
    if not extension or not re.fullmatch(r"\.[a-z0-9]{1,8}", extension):
        extension = mimetypes.guess_extension(normalized_type) or ".bin"
    token = f"{uuid.uuid4().hex}{extension}"
    (asset_root() / token).write_bytes(raw)
    return f"ingest-asset://{token}"


def read_asset(reference: str) -> tuple[bytes, str, str] | None:
    token = (reference or "").removeprefix("ingest-asset://").strip()
    if not _TOKEN_RE.fullmatch(token):
        return None
    path = asset_root() / token
    if not path.is_file():
        return None
    content_type = mimetypes.guess_type(token)[0] or "application/octet-stream"
    return path.read_bytes(), token, content_type
