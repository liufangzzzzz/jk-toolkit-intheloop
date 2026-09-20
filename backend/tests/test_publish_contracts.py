from __future__ import annotations

from typing import Any

from agents.intheloop.wechat.client import WeChatApiClient
from agents.intheloop.wechat.config import WeChatConfig


def test_wechat_draft_uses_official_draft_contract(monkeypatch) -> None:
    client = WeChatApiClient(
        WeChatConfig(
            app_id="wx-test",
            app_secret="secret",
            upload_mode="real",
            api_base="https://api.weixin.qq.com/cgi-bin",
            account_label="test",
            thumb_media_id="thumb",
            default_cover_image_path=None,
        )
    )
    captured: dict[str, Any] = {}
    monkeypatch.setattr(client, "get_access_token", lambda **_: "token")

    def fake_post(url, params, *, files=None, json_payload=None):
        captured.update(url=url, params=params, files=files, json=json_payload)
        return {"media_id": "draft-media"}

    monkeypatch.setattr(client, "_post_json", fake_post)
    media_id = client.draft_add([{"title": "测试", "content": "<p>正文</p>"}])

    assert media_id == "draft-media"
    assert captured["url"] == "https://api.weixin.qq.com/cgi-bin/draft/add"
    assert captured["params"] == {"access_token": "token"}
    assert captured["json"] == {"articles": [{"title": "测试", "content": "<p>正文</p>"}]}
