"""微信公众号接入配置（多账号：config/wechat-accounts.json）。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, Optional

from .errors import WECHAT_CONFIG_ERROR, WeChatServiceError

UploadMode = Literal["stub", "real"]

_DEFAULT_API_BASE = "https://api.weixin.qq.com/cgi-bin"


@dataclass(frozen=True)
class WeChatConfig:
    app_id: str
    app_secret: str
    upload_mode: UploadMode
    api_base: str
    account_label: str
    thumb_media_id: Optional[str]
    default_cover_image_path: Optional[str]
    account_id: str = ""

    def require_credentials(self) -> None:
        if not self.app_id or not self.app_secret:
            raise WeChatServiceError(
                "微信公众号配置未完成：请在「公众号配置」填写 AppID 与 AppSecret",
                WECHAT_CONFIG_ERROR,
            )


def get_wechat_upload_mode() -> UploadMode:
    """读取上传模式；兼容历史拼写错误 ECHAT_UPLOAD_MODE。"""
    mode_raw = (
        os.environ.get("WECHAT_UPLOAD_MODE", "").strip()
        or os.environ.get("ECHAT_UPLOAD_MODE", "").strip()
        or "stub"
    ).lower()
    if mode_raw not in ("stub", "real"):
        return "stub"
    return mode_raw  # type: ignore[return-value]


def _api_base_from_env() -> str:
    return (
        os.environ.get("WECHAT_API_BASE", _DEFAULT_API_BASE).strip()
        or _DEFAULT_API_BASE
    ).rstrip("/")


def load_wechat_config(account_id: str) -> WeChatConfig:
    """
    按账号 id 加载微信凭据（唯一来源：wechat-accounts.json）。
    不再从 WECHAT_APP_ID / WECHAT_APP_SECRET 读取。
    """
    from agents.intheloop.wechat_accounts import load_intheloop_wechat_accounts

    cfg = load_intheloop_wechat_accounts()
    entry = cfg.get_account(account_id)
    mode_raw = get_wechat_upload_mode()
    return WeChatConfig(
        app_id=entry.app_id.strip(),
        app_secret=entry.app_secret.strip(),
        upload_mode=mode_raw,  # type: ignore[assignment]
        api_base=_api_base_from_env(),
        account_label=entry.name.strip() or entry.id,
        thumb_media_id=None,
        default_cover_image_path=None,
        account_id=entry.id,
    )
