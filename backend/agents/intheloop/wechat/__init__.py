"""微信公众号开放平台接入（P1：可配置 stub/real）。"""
from .config import WeChatConfig, load_wechat_config
from .errors import WeChatServiceError
from .service import WeChatDraftService, get_wechat_draft_service

__all__ = [
    "WeChatConfig",
    "WeChatDraftService",
    "WeChatServiceError",
    "get_wechat_draft_service",
    "load_wechat_config",
]
