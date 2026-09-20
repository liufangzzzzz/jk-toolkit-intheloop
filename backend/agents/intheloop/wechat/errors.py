"""微信公众号 API 业务错误（稳定 error_code 供 API/前端展示）。"""
from __future__ import annotations


class WeChatServiceError(Exception):
    def __init__(self, message: str, code: str, *, errcode: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.errcode = errcode


WECHAT_CONFIG_ERROR = "WECHAT_CONFIG_ERROR"
WECHAT_TOKEN_ERROR = "WECHAT_TOKEN_ERROR"
WECHAT_API_ERROR = "WECHAT_API_ERROR"
WECHAT_IP_WHITELIST = "WECHAT_IP_WHITELIST"
WECHAT_UPLOAD_ERROR = "WECHAT_UPLOAD_ERROR"
WECHAT_COVER_REQUIRED = "WECHAT_COVER_REQUIRED"
