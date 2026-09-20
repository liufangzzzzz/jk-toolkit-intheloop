"""InTheLoop-owned reader for selectable WeChat accounts.

The data file stays compatible with the workbench account settings page, but
this module deliberately avoids importing the wechat_layout tab. Future edits
to that tab should not change InTheLoop runtime behavior.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent.parent / "config" / "wechat-accounts.json"
)


class InTheLoopWechatAccountEntry(BaseModel):
    id: str
    name: str
    app_id: str
    app_secret: str = ""
    enabled: bool = True
    last_test_ok: bool = False
    last_tested_at: Optional[str] = None

    def is_selectable(self) -> bool:
        return self.enabled and self.last_test_ok


class InTheLoopWechatAccountsConfig(BaseModel):
    version: int = 1
    default_account_id: str = ""
    accounts: List[InTheLoopWechatAccountEntry] = Field(default_factory=list)

    def get_account(self, account_id: str) -> InTheLoopWechatAccountEntry:
        aid = (account_id or "").strip()
        for account in self.accounts:
            if account.id == aid:
                return account
        raise ValueError(f"公众号账号不存在：{account_id!r}")

    def selectable_accounts(self) -> List[InTheLoopWechatAccountEntry]:
        return [account for account in self.accounts if account.is_selectable()]


def load_intheloop_wechat_accounts() -> InTheLoopWechatAccountsConfig:
    if not _CONFIG_PATH.is_file():
        raise ValueError("未找到 config/wechat-accounts.json，请先完成公众号账号配置")
    raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    cfg = InTheLoopWechatAccountsConfig.model_validate(raw)
    if not cfg.accounts:
        raise ValueError("至少配置一个公众号账号")
    return cfg


def assert_intheloop_account_selectable(
    account_id: str,
) -> InTheLoopWechatAccountEntry:
    cfg = load_intheloop_wechat_accounts()
    account = cfg.get_account(account_id)
    if not account.is_selectable():
        if account.enabled and account.app_id.strip() and account.app_secret.strip():
            raise ValueError(
                f"账号「{account.name}」凭据检测未通过，请先在账号配置中完成检测"
            )
        raise ValueError(f"账号「{account.name}」不可用：须启用且检测通过")
    return account


def selectable_intheloop_accounts() -> tuple[List[InTheLoopWechatAccountEntry], str]:
    cfg = load_intheloop_wechat_accounts()
    return cfg.selectable_accounts(), cfg.default_account_id
