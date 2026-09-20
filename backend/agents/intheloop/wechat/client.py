"""微信公众号 CGI 低层 HTTP 客户端（同步，供 LangGraph 节点调用）。"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from .config import WeChatConfig
from .image_upload import mime_from_filename
from .errors import (
    WECHAT_API_ERROR,
    WECHAT_COVER_REQUIRED,
    WECHAT_IP_WHITELIST,
    WECHAT_TOKEN_ERROR,
    WeChatServiceError,
)

logger = logging.getLogger(__name__)

_IP_WHITELIST_CODES = {40164, 61004}
_TRANSIENT_API_CODES = {-1, 45009, 45011, 45028}


class WeChatApiClient:
    def __init__(self, config: WeChatConfig) -> None:
        self._config = config
        self._access_token: Optional[str] = None
        self._expire_at: int = 0

    def get_access_token(self, *, force: bool = False) -> str:
        now = int(time.time())
        if not force and self._access_token and now < self._expire_at - 300:
            return self._access_token

        self._config.require_credentials()
        url = f"{self._config.api_base}/token"
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                url,
                params={
                    "grant_type": "client_credential",
                    "appid": self._config.app_id,
                    "secret": self._config.app_secret,
                },
            )
            data = resp.json()

        if data.get("errcode"):
            self._raise_api("token", data)

        token = data.get("access_token")
        if not token:
            raise WeChatServiceError(
                "微信 access_token 响应缺少 access_token",
                WECHAT_TOKEN_ERROR,
            )

        self._access_token = token
        self._expire_at = now + int(data.get("expires_in", 7200))
        logger.info(
            "微信 access_token 已刷新",
            extra={"account_label": self._config.account_label},
        )
        return token

    def uploadimg(self, image_bytes: bytes, filename: str = "image.jpg") -> str:
        """上传图文消息内图片，返回微信 CDN URL（仅 jpg/png，<1MB）。"""
        url = f"{self._config.api_base}/media/uploadimg"
        content_type = mime_from_filename(filename)
        files = {"media": (filename, image_bytes, content_type)}
        data = self._api_call_with_retry(
            "uploadimg",
            lambda token: self._post_json(url, {"access_token": token}, files=files),
        )
        cdn_url = data.get("url")
        if not cdn_url:
            raise WeChatServiceError(
                "uploadimg 响应缺少 url",
                WECHAT_API_ERROR,
                errcode=data.get("errcode"),
            )
        return str(cdn_url)

    def add_material_image(self, image_bytes: bytes, filename: str = "cover.jpg") -> str:
        """上传永久图片素材，返回 thumb_media_id。"""
        url = f"{self._config.api_base}/material/add_material"
        content_type = mime_from_filename(filename)
        files = {"media": (filename, image_bytes, content_type)}
        data = self._api_call_with_retry(
            "add_material",
            lambda token: self._post_json(
                url,
                {"access_token": token, "type": "image"},
                files=files,
            ),
        )
        media_id = data.get("media_id")
        if not media_id:
            raise WeChatServiceError(
                "add_material 响应缺少 media_id",
                WECHAT_API_ERROR,
                errcode=data.get("errcode"),
            )
        return str(media_id)

    def add_material_image_url(
        self, image_bytes: bytes, filename: str = "image.gif"
    ) -> str:
        """上传永久图片素材，返回可在正文 HTML 中使用的 url（用于 GIF 动图等）。"""
        url = f"{self._config.api_base}/material/add_material"
        content_type = mime_from_filename(filename)
        files = {"media": (filename, image_bytes, content_type)}
        data = self._api_call_with_retry(
            "add_material",
            lambda token: self._post_json(
                url,
                {"access_token": token, "type": "image"},
                files=files,
            ),
        )
        cdn_url = data.get("url")
        if not cdn_url:
            raise WeChatServiceError(
                "add_material 响应缺少 url",
                WECHAT_API_ERROR,
                errcode=data.get("errcode"),
            )
        return str(cdn_url)

    def draft_add(self, articles: list[dict[str, Any]]) -> str:
        """新增草稿，返回 media_id。"""
        url = f"{self._config.api_base}/draft/add"
        data = self._api_call_with_retry(
            "draft_add",
            lambda token: self._post_json(
                url,
                {"access_token": token},
                json_payload={"articles": articles},
            ),
        )
        media_id = data.get("media_id")
        if not media_id:
            raise WeChatServiceError(
                "draft_add 响应缺少 media_id",
                WECHAT_API_ERROR,
                errcode=data.get("errcode"),
            )
        return str(media_id)

    def load_cover_bytes(
        self,
        registry_images: list[tuple[str, bytes, str]],
    ) -> tuple[bytes, str]:
        """解析封面图字节：预置 media_id 由调用方处理；此处返回需上传的字节。"""
        if registry_images:
            _, data, fname = registry_images[0]
            return data, fname
        path = self._config.default_cover_image_path
        if path:
            p = Path(path)
            if p.is_file():
                return p.read_bytes(), p.name
        raise WeChatServiceError(
            "缺少封面图：请配置 WECHAT_THUMB_MEDIA_ID、正文中至少一张图，"
            "或 WECHAT_DEFAULT_COVER_IMAGE_PATH 指向本地 JPG/PNG",
            WECHAT_COVER_REQUIRED,
        )

    def _raise_api(self, api_name: str, data: Dict[str, Any]) -> None:
        errcode = int(data.get("errcode", -1))
        errmsg = str(data.get("errmsg", ""))
        if errcode in _IP_WHITELIST_CODES:
            raise WeChatServiceError(
                f"微信 API [{api_name}] IP 未在白名单 (errcode={errcode}): {errmsg}。"
                "请在公众平台配置服务器 IP 白名单。",
                WECHAT_IP_WHITELIST,
                errcode=errcode,
            )
        if errcode in (40001, 42001, 40014):
            raise WeChatServiceError(
                f"微信 access_token 失效 (errcode={errcode}): {errmsg}",
                WECHAT_TOKEN_ERROR,
                errcode=errcode,
            )
        raise WeChatServiceError(
            f"微信 API [{api_name}] 失败 (errcode={errcode}): {errmsg}",
            WECHAT_API_ERROR,
            errcode=errcode,
        )

    def _post_json(
        self,
        url: str,
        params: Dict[str, Any],
        *,
        files: Optional[Dict[str, Any]] = None,
        json_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, params=params, files=files, json=json_payload)
            return resp.json()

    def _api_call_with_retry(self, api_name: str, caller) -> Dict[str, Any]:
        forced_token_refresh = False
        for attempt in range(3):
            token = self.get_access_token(force=forced_token_refresh)
            try:
                data = caller(token)
            except (httpx.TimeoutException, httpx.TransportError, httpx.RemoteProtocolError) as exc:
                if attempt < 2:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise WeChatServiceError(
                    f"微信 API [{api_name}] 网络异常: {exc}",
                    WECHAT_API_ERROR,
                ) from exc

            errcode = int(data.get("errcode", 0) or 0)
            if errcode == 0:
                return data
            if errcode in (40001, 42001, 40014) and not forced_token_refresh:
                forced_token_refresh = True
                continue
            if errcode in _TRANSIENT_API_CODES and attempt < 2:
                time.sleep(0.5 * (2 ** attempt))
                continue
            self._raise_api(api_name, data)
        raise WeChatServiceError(f"微信 API [{api_name}] 重试后仍失败", WECHAT_API_ERROR)
