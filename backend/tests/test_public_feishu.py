from __future__ import annotations

from pathlib import Path

import pytest

from agents.intheloop.feishu.errors import FeishuServiceError
from agents.intheloop.feishu.public_browser import (
    _markdown_to_word_result,
    validate_public_feishu_url,
)
from agents.intheloop.feishu.public_image_store import (
    fetch_public_image,
    store_public_image,
)


def test_public_url_validation_accepts_feishu_docx_and_wiki() -> None:
    assert validate_public_feishu_url("https://example.feishu.cn/docx/abc").endswith("/docx/abc")
    assert validate_public_feishu_url("https://example.feishu.cn/wiki/abc").endswith("/wiki/abc")


@pytest.mark.parametrize(
    "url",
    [
        "http://example.feishu.cn/docx/abc",
        "https://example.com/docx/abc",
        "https://example.feishu.cn:8443/docx/abc",
        "https://example.feishu.cn/base/abc",
    ],
)
def test_public_url_validation_rejects_unsafe_or_unsupported_urls(url: str) -> None:
    with pytest.raises(FeishuServiceError):
        validate_public_feishu_url(url)


def test_markdown_conversion_keeps_images_and_skips_files_and_video() -> None:
    markdown = """# 测试标题

作者｜小明

## 01. 第一节

![](<public-image://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa>)

[video.mp4](browser-asset://file/123)

<iframe src="https://example.com/video"></iframe>
"""
    result = _markdown_to_word_result(markdown, "测试标题")
    assert result.document_title == "测试标题"
    assert sum(block.block_type == "image" for block in result.raw_block_list) == 1
    assert all("video.mp4" not in block.text for block in result.raw_block_list)


def test_table_is_collapsed_to_one_warning_block() -> None:
    result = _markdown_to_word_result(
        "# title\n\n| A | B |\n| --- | --- |\n| 1 | 2 |", "title"
    )
    assert sum(block.block_type == "table" for block in result.raw_block_list) == 1


def test_public_image_store_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 1x1 transparent PNG
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c6360606060000000050001a5f645400000000049454e44ae426082"
    )
    monkeypatch.setenv("ITL_PUBLIC_IMAGE_CACHE_DIR", str(tmp_path))
    ref = store_public_image(png)
    fetched = fetch_public_image(ref)
    assert fetched is not None
    assert fetched[0] == png
    assert fetched[2] == "image/png"
