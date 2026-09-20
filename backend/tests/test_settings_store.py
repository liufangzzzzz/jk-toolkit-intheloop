from app.main import app
from app.modules.wechat_draft.service import public_settings as public_wechat_settings
from app.modules.website_ingest.publisher import connection_status
from app.settings_store import load_settings, update_settings
from fastapi.testclient import TestClient


def test_wechat_secret_is_saved_but_never_returned(tmp_path, monkeypatch):
    monkeypatch.setenv("ITL_SETTINGS_PATH", str(tmp_path / "settings.json"))
    update_settings(
        "wechat",
        app_id="wx123",
        app_secret="super-secret",
        account_name="测试公众号",
        tested=True,
    )

    assert load_settings()["wechat"]["app_secret"] == "super-secret"
    public = public_wechat_settings()
    assert public["app_id"] == "wx123"
    assert public["has_secret"] is True
    assert "app_secret" not in public


def test_website_access_key_is_saved_but_never_returned(tmp_path, monkeypatch):
    monkeypatch.setenv("ITL_SETTINGS_PATH", str(tmp_path / "settings.json"))
    update_settings(
        "website",
        access_key="private-key",
        nickname="编辑甲",
        author_id=12,
        column_id=34,
        tested=True,
    )

    public = connection_status()
    assert public["connected"] is True
    assert public["nickname"] == "编辑甲"
    assert "access_key" not in public


def test_first_run_and_wechat_web_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("TOOLKIT_INTHELOOP_PASSWORD", raising=False)
    monkeypatch.delenv("ITL_ACCESS_PASSWORD", raising=False)
    monkeypatch.delenv("ITL_SESSION_SECRET", raising=False)
    monkeypatch.setenv("ITL_COOKIE_SECURE", "false")
    monkeypatch.setenv("ITL_SETTINGS_PATH", str(tmp_path / "settings.json"))
    client = TestClient(app)

    setup = client.post("/api/v1/auth/setup", json={"password": "test-password-123"})
    assert setup.status_code == 200

    saved = client.put(
        "/api/v1/wechat-draft/settings",
        json={"app_id": "wx-web", "app_secret": "secret-web", "account_name": "网页配置"},
    )
    assert saved.status_code == 200
    assert saved.json() == {
        "app_id": "wx-web",
        "has_secret": True,
        "account_name": "网页配置",
        "tested": False,
    }
