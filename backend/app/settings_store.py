from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_DEFAULTS: dict[str, Any] = {
    "auth": {},
    "wechat": {"app_id": "", "app_secret": "", "account_name": "In The Loop.具身现场", "tested": False},
    "website": {"access_key": "", "nickname": "", "author_id": None, "column_id": 0, "tested": False},
    "real_upload_enabled": False,
}


def settings_path() -> Path:
    configured = os.environ.get("ITL_SETTINGS_PATH", "").strip()
    return Path(configured) if configured else Path.cwd() / ".local-data" / "toolkit-settings.json"


def load_settings() -> dict[str, Any]:
    with _LOCK:
        data = deepcopy(_DEFAULTS)
        path = settings_path()
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    for key, value in loaded.items():
                        if isinstance(value, dict) and isinstance(data.get(key), dict):
                            data[key].update(value)
                        else:
                            data[key] = value
            except (OSError, ValueError):
                pass
        return data


def save_settings(data: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(temp, 0o600)
        temp.replace(path)
        return data


def update_settings(section: str | None = None, **values: Any) -> dict[str, Any]:
    with _LOCK:
        data = load_settings()
        if section:
            current = data.setdefault(section, {})
            if not isinstance(current, dict):
                current = {}
                data[section] = current
            current.update(values)
        else:
            data.update(values)
        return save_settings(data)
