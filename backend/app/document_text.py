"""Text-only Word import for Audio Studio."""
from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from pathlib import Path

import mammoth

MAX_DOCUMENT_BYTES = 60 * 1024 * 1024


def _convert_legacy_doc(raw: bytes, filename: str) -> bytes:
    executable = shutil.which('soffice') or shutil.which('libreoffice')
    if not executable:
        raise ValueError('当前环境尚未安装 LibreOffice，暂时无法读取 .doc 文件')
    with tempfile.TemporaryDirectory(prefix='audio-doc-') as temp_dir:
        source = Path(temp_dir) / (Path(filename).name or 'document.doc')
        source.write_bytes(raw)
        process = subprocess.run(
            [executable, '--headless', '--convert-to', 'docx', '--outdir', temp_dir, str(source)],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        converted = source.with_suffix('.docx')
        if process.returncode != 0 or not converted.is_file():
            raise ValueError('.doc 转换失败，请确认文件未损坏')
        return converted.read_bytes()


def parse_word_text(raw: bytes, filename: str) -> tuple[str, str]:
    if not raw or len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError('Word 文件为空或超过 60MB')
    suffix = Path(filename or '').suffix.lower()
    if suffix not in {'.docx', '.doc'}:
        raise ValueError('只支持 .docx 或 .doc 文件')
    docx = _convert_legacy_doc(raw, filename) if suffix == '.doc' else raw
    text = mammoth.extract_raw_text(io.BytesIO(docx)).value.strip()
    if not text:
        raise ValueError('Word 文件中没有读取到文字')
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), '')
    title = first_line[:300] or Path(filename).stem
    return title, text
