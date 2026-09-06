"""点路径配置读取：对插件原始配置 dict 提供安全访问与类型转换。"""

from __future__ import annotations

from typing import Any


class ConfigView:
    """基于点路径的配置访问器，缺失字段返回默认值，不抛异常。"""

    def __init__(self, raw: Any):
        self.raw = raw if isinstance(raw, dict) else {}

    def get(self, dotted: str, default: Any = None) -> Any:
        value = self._walk(dotted)
        return default if value is None else value

    def _walk(self, dotted: str) -> Any:
        current: Any = self.raw
        for part in dotted.split("."):
            if isinstance(current, dict):
                if part not in current or current.get(part) is None:
                    return None
                current = current.get(part)
            else:
                getter = getattr(current, "get", None)
                if not callable(getter):
                    return None
                value = getter(part)
                if value is None:
                    return None
                current = value
            if current is None:
                return None
        return current

    def bool(self, dotted: str, default: bool) -> bool:
        value = self.get(dotted, default)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "开", "开启"}
        return bool(value)

    def int(self, dotted: str, default: int) -> int:
        try:
            return int(self.get(dotted, default))
        except Exception:
            return default

    def float(self, dotted: str, default: float) -> float:
        try:
            return float(self.get(dotted, default))
        except Exception:
            return default

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        current = self.raw
        for part in parts[:-1]:
            nxt = current.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                current[part] = nxt
            current = nxt
        current[parts[-1]] = value
