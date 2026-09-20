"""Small image MIME sniffer owned by InTheLoop."""
from __future__ import annotations

from typing import Optional


def sniff_image_mime_from_bytes(data: bytes) -> Optional[str]:
    if not data:
        return None
    head = data[:16]
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if head.startswith(b"BM"):
        return "image/bmp"
    if head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"\x01\x00\x00\x00") or head.startswith(b"\xd7\xcd\xc6\x9a"):
        return "image/wmf"
    if head.startswith(b"\x01\x00\x00\x00") or head.startswith(b" EMF"):
        return "image/emf"
    return None
