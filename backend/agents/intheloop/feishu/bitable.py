"""飞书多维表格（Bitable）客户端 — 早知道分区专用凭据。"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx

from .errors import (
    FEISHU_API_ERROR,
    FEISHU_CONFIG_ERROR,
    FEISHU_PERMISSION_DENIED,
    FEISHU_TOKEN_ERROR,
    FeishuServiceError,
)

logger = logging.getLogger(__name__)

_BASE = "https://open.feishu.cn/open-apis"
_SHANGHAI = ZoneInfo("Asia/Shanghai")


class ZaozhidaoFeishuBitableClient:
    """早知道飞书排班表客户端。

    优先使用 ZAOZHIDAO_FEISHU_APP_ID/SECRET；
    若未配置则 fallback 到共用的 FEISHU_APP_ID/SECRET（同一飞书应用）。
    """

    def __init__(self) -> None:
        self.app_id = (
            os.environ.get("ZAOZHIDAO_FEISHU_APP_ID", "").strip()
            or os.environ.get("FEISHU_APP_ID", "").strip()
        )
        self.app_secret = (
            os.environ.get("ZAOZHIDAO_FEISHU_APP_SECRET", "").strip()
            or os.environ.get("FEISHU_APP_SECRET", "").strip()
        )
        self._access_token: Optional[str] = None
        self._expire_at: int = 0

    @staticmethod
    def credentials_configured() -> bool:
        return bool(
            (os.environ.get("ZAOZHIDAO_FEISHU_APP_ID", "").strip()
             or os.environ.get("FEISHU_APP_ID", "").strip())
            and (os.environ.get("ZAOZHIDAO_FEISHU_APP_SECRET", "").strip()
                 or os.environ.get("FEISHU_APP_SECRET", "").strip())
        )

    async def get_access_token(self) -> str:
        now = int(time.time())
        if self._access_token and now < self._expire_at - 60:
            return self._access_token

        if not self.app_id or not self.app_secret:
            raise FeishuServiceError(
                "早知道飞书配置未完成：请设置 ZAOZHIDAO_FEISHU_APP_ID 和 ZAOZHIDAO_FEISHU_APP_SECRET",
                FEISHU_CONFIG_ERROR,
            )

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_BASE}/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            data = resp.json()

        if data.get("code") != 0:
            raise FeishuServiceError(
                f"早知道飞书 Token 获取失败 [{data.get('code')}]: {data.get('msg', '')}",
                FEISHU_TOKEN_ERROR,
            )

        self._access_token = data["tenant_access_token"]
        self._expire_at = now + int(data.get("expire", 7200))
        logger.info("早知道分区 tenant_access_token 已刷新")
        return self._access_token

    async def list_records(
        self,
        *,
        app_token: str,
        table_id: str,
        filter_expr: Optional[str] = None,
        page_size: int = 5,
    ) -> List[Dict[str, Any]]:
        token = await self.get_access_token()
        params: Dict[str, Any] = {"page_size": page_size}
        if filter_expr:
            params["filter"] = filter_expr

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(
                f"{_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )

        if resp.status_code == 403:
            raise FeishuServiceError(
                "飞书多维表格权限不足：请为应用开通 bitable:app 相关权限并发布应用",
                FEISHU_PERMISSION_DENIED,
            )

        try:
            data = resp.json()
        except Exception as exc:
            raise FeishuServiceError(
                f"飞书 Bitable 响应非 JSON（HTTP {resp.status_code}）",
                FEISHU_API_ERROR,
            ) from exc

        if data.get("code") != 0:
            code = int(data.get("code", 0))
            msg = data.get("msg", "未知错误")
            if "permission" in msg.lower():
                raise FeishuServiceError(
                    f"飞书 Bitable 权限不足 [{code}]: {msg}",
                    FEISHU_PERMISSION_DENIED,
                )
            raise FeishuServiceError(
                f"飞书 Bitable API 错误 [{code}]: {msg}",
                FEISHU_API_ERROR,
            )

        items = (data.get("data") or {}).get("items") or []
        return [x for x in items if isinstance(x, dict)]

    @staticmethod
    def today_iso(*, tz: ZoneInfo = _SHANGHAI) -> str:
        return datetime.now(tz).date().isoformat()

    @staticmethod
    def tomorrow_iso(*, tz: ZoneInfo = _SHANGHAI) -> str:
        today = datetime.now(tz).date()
        return (today + timedelta(days=1)).isoformat()

    @staticmethod
    def build_date_filter(date_field: str, iso_date: str) -> str:
        """文本型日期字段的 Bitable filter。"""
        return f'CurrentValue.[{date_field}] = "{iso_date}"'

    @staticmethod
    def parse_field_to_iso_date(
        raw: Any,
        *,
        tz: ZoneInfo = _SHANGHAI,
    ) -> Optional[str]:
        """
        将飞书 Bitable 日期字段值规范为 YYYY-MM-DD。

        支持：毫秒/秒时间戳、ISO 字符串、含 value 的字典、仅日期 dict。
        """
        if raw is None:
            return None
        if isinstance(raw, dict):
            if "value" in raw:
                return ZaozhidaoFeishuBitableClient.parse_field_to_iso_date(
                    raw.get("value"), tz=tz
                )
            y = raw.get("year") or raw.get("Year")
            m = raw.get("month") or raw.get("Month")
            d = raw.get("day") or raw.get("Day")
            if y and m and d:
                try:
                    return date(int(y), int(m), int(d)).isoformat()
                except (TypeError, ValueError):
                    return None
        if isinstance(raw, (int, float)):
            ts = float(raw)
            if ts > 1e12:
                ts /= 1000.0
            elif ts < 1e9:
                return None
            try:
                return datetime.fromtimestamp(ts, tz=tz).date().isoformat()
            except (OSError, OverflowError, ValueError):
                return None
        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                return None
            if s.isdigit():
                return ZaozhidaoFeishuBitableClient.parse_field_to_iso_date(
                    int(s), tz=tz
                )
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
                try:
                    return datetime.strptime(s[:10], fmt).date().isoformat()
                except ValueError:
                    continue
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(
                    tz
                ).date().isoformat()
            except ValueError:
                return None
        return None

    @staticmethod
    def extract_person_name(
        record: Dict[str, Any],
        *,
        name_field: str,
    ) -> str:
        fields = record.get("fields") or {}
        raw = fields.get(name_field)
        if isinstance(raw, list) and raw:
            first = raw[0]
            if isinstance(first, dict):
                return str(first.get("name") or "").strip()
            return str(first).strip()
        if isinstance(raw, dict):
            return str(raw.get("name") or "").strip()
        if raw is not None:
            return str(raw).strip()
        return ""

    async def fetch_duty_person_for_date(
        self,
        *,
        app_token: str,
        table_id: str,
        date_field: str,
        name_field: str,
        target_date: str,
        date_field_type: str = "date",
        view_id: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        按目标日期查询排班人员。

        - date_field_type=date：飞书日期列为时间戳，拉取记录后在本地按 YYYY-MM-DD 匹配
        - date_field_type=text：使用 Bitable 字符串 filter
        """
        dtype = (date_field_type or "date").strip().lower()
        items: List[Dict[str, Any]] = []

        if dtype == "text":
            filter_expr = self.build_date_filter(date_field, target_date)
            items = await self.list_records(
                app_token=app_token,
                table_id=table_id,
                filter_expr=filter_expr,
                page_size=20,
            )
        else:
            scanned = await self.list_records(
                app_token=app_token,
                table_id=table_id,
                filter_expr=None,
                page_size=500,
            )
            matched: List[Dict[str, Any]] = []
            for rec in scanned:
                fields = rec.get("fields") or {}
                iso = self.parse_field_to_iso_date(fields.get(date_field))
                if iso == target_date:
                    matched.append(rec)
            if not matched:
                logger.info(
                    "排班表未命中目标日期",
                    extra={
                        "target_date": target_date,
                        "date_field": date_field,
                        "date_field_type": dtype,
                        "view_id": view_id or "-",
                        "scanned": len(scanned),
                    },
                )
                return None
            items = matched

        if not items:
            return None

        person_name = self.extract_person_name(items[0], name_field=name_field)
        fields = items[0].get("fields") or {}
        parsed_date = self.parse_field_to_iso_date(fields.get(date_field))
        return {
            "record_id": items[0].get("record_id", ""),
            "target_date": target_date,
            "parsed_date": parsed_date,
            "person_name": person_name,
            "raw_fields": fields,
        }
