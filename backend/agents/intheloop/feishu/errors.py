"""飞书接入层稳定错误码（与 routes / 前端展示对齐）。"""
from __future__ import annotations


class FeishuServiceError(RuntimeError):
    """可映射为 HTTP 400 + error_code 的业务异常。"""

    def __init__(self, message: str, code: str) -> None:
        self.code = code
        super().__init__(message)


# 稳定 error_code 常量
FEISHU_CONFIG_ERROR = "FEISHU_CONFIG_ERROR"
FEISHU_TOKEN_ERROR = "FEISHU_TOKEN_ERROR"
FEISHU_LINK_INVALID = "FEISHU_LINK_INVALID"
FEISHU_UNSUPPORTED_TYPE = "FEISHU_UNSUPPORTED_TYPE"
FEISHU_PERMISSION_DENIED = "FEISHU_PERMISSION_DENIED"
FEISHU_EXPORT_TIMEOUT = "FEISHU_EXPORT_TIMEOUT"
FEISHU_EXPORT_FAILED = "FEISHU_EXPORT_FAILED"
FEISHU_DOC_NOT_FOUND = "FEISHU_DOC_NOT_FOUND"
FEISHU_API_ERROR = "FEISHU_API_ERROR"
