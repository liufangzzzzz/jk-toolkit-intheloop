from __future__ import annotations

import pytest

from app.geekpark_auth import normalize_author_id


def test_normalize_author_id_keeps_uuid_string() -> None:
    author_id = "66bba2b4-3479-4f44-b134-66f1c67c68e7"

    assert normalize_author_id(author_id) == author_id


def test_normalize_author_id_preserves_legacy_numeric_id() -> None:
    assert normalize_author_id("123") == 123
    assert normalize_author_id(123) == 123


@pytest.mark.parametrize("value", [None, True, "", "   "])
def test_normalize_author_id_rejects_empty_or_boolean_values(value: object) -> None:
    with pytest.raises(ValueError, match="无法取得官网作者信息"):
        normalize_author_id(value)
