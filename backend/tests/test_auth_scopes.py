from starlette.requests import Request
from starlette.responses import Response

from app.auth import auth_enabled, create_session_cookie, is_authenticated, set_initial_password, setup_required, verify_password


def _request(cookie_header: str = "") -> Request:
    headers = [(b"cookie", cookie_header.encode())] if cookie_header else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def test_tab_passwords_are_scoped(monkeypatch):
    monkeypatch.setenv("TOOLKIT_INTHELOOP_PASSWORD", "inside-one")
    monkeypatch.setenv("TOOLKIT_RESEARCH_PASSWORD", "inside-two")
    monkeypatch.setenv("ITL_SESSION_SECRET", "test-secret")

    assert auth_enabled("intheloop")
    assert verify_password("inside-one", "intheloop")
    assert not verify_password("inside-one", "research")

    response = Response()
    create_session_cookie(response, "research")
    cookie = response.headers["set-cookie"].split(";", 1)[0]

    assert is_authenticated(_request(cookie), "research")
    assert not is_authenticated(_request(cookie), "intheloop")


def test_legacy_intheloop_password_is_still_supported(monkeypatch):
    monkeypatch.delenv("TOOLKIT_INTHELOOP_PASSWORD", raising=False)
    monkeypatch.setenv("ITL_ACCESS_PASSWORD", "legacy-password")

    assert auth_enabled("intheloop")
    assert verify_password("legacy-password", "intheloop")


def test_first_run_password_is_persisted_and_verified(tmp_path, monkeypatch):
    monkeypatch.delenv("TOOLKIT_INTHELOOP_PASSWORD", raising=False)
    monkeypatch.delenv("ITL_ACCESS_PASSWORD", raising=False)
    monkeypatch.setenv("ITL_SETTINGS_PATH", str(tmp_path / "settings.json"))

    assert setup_required("intheloop")
    set_initial_password("a-strong-password")

    assert not setup_required("intheloop")
    assert auth_enabled("intheloop")
    assert verify_password("a-strong-password", "intheloop")
    assert not verify_password("wrong-password", "intheloop")


def test_first_run_does_not_unlock_protected_routes(tmp_path, monkeypatch):
    monkeypatch.delenv("TOOLKIT_INTHELOOP_PASSWORD", raising=False)
    monkeypatch.delenv("ITL_ACCESS_PASSWORD", raising=False)
    monkeypatch.setenv("ITL_SETTINGS_PATH", str(tmp_path / "settings.json"))

    assert setup_required("intheloop")
    assert not is_authenticated(_request(), "intheloop")
