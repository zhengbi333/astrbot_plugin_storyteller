"""UI 状态：选项卡布局（顺序）的存储与校验。

设计要点（独立实现，不与外部插件雷同）：
- 仅保存「选项卡顺序」这一项前端布局状态，其它 UI 偏好走 config；
- 存储文件 ui.json（插件数据目录），读写失败静默降级为默认顺序；
- 校验规则：必须是全部已知选项卡的一个排列（无缺、无重、无未知项），
  否则视为非法并拒绝保存，防止脏数据破坏导航。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_UI_FILE = "ui.json"

# 与前端 app.js 的 NAV 完全一致的选项卡键集合（顺序即默认布局）
# alpha-0.57 起移除「模型」选项卡（模型设置已分散到各模块页内），16 → 15
# alpha-0.123 起新增「发送」（发送缓冲与抢话），19 → 20
# alpha-0.125 起「发送」挪到「润色」之前（用户要求，发送相关设置紧挨拦＆改）
# alpha-0.130 起新增「清障」（模块自检），20 → 21
# alpha-0.137 起新增「鸣谢」（末尾），21 → 22
# alpha-0.145 起重新新增「模型」（全插件模型配置集中点，清障之后），22 → 23
# alpha-0.148 起新增「生图」（模型之后），23 → 24
KNOWN_TABS: list[str] = [
    "overview",
    "troubleshoot",
    "models",
    "image",
    "appearance",
    "intercept",
    "send",
    "rewrite",
    "debounce",
    "identity",
    "relationship",
    "voice",
    "persona",
    "presence",
    "schedule",
    "wardrobe",
    "mind",
    "memory",
    "proactive",
    "emoji",
    "token",
    "settings",
    "debug",
    "thanks",
]


def sanitize_tab_order(order: Any) -> list[str] | None:
    """校验选项卡顺序：合法返回规范化列表，非法返回 None。

    合法定义：列表且恰好包含全部已知选项卡键、无重复、无未知键。
    """
    if not isinstance(order, list):
        return None
    if len(order) != len(KNOWN_TABS):
        return None
    known = set(KNOWN_TABS)
    seen: set[str] = set()
    out: list[str] = []
    for key in order:
        if not isinstance(key, str) or key not in known or key in seen:
            return None
        seen.add(key)
        out.append(key)
    return out


class UiStateStore:
    """ui.json 的读写（目前仅选项卡顺序一项）。"""

    def __init__(self, data_dir: Path):
        self._file = Path(data_dir) / _UI_FILE
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._file.exists():
                raw = json.loads(self._file.read_text(encoding="utf-8-sig"))
                if isinstance(raw, dict):
                    self._data = raw
        except Exception:
            self._data = {}

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def load_order(self) -> list[str] | None:
        """读取已保存的选项卡顺序；无自定义布局时返回 None（前端用默认）。"""
        order = sanitize_tab_order(self._data.get("tab_order"))
        return order

    def save_order(self, order: Any) -> bool:
        """保存选项卡顺序。非法顺序拒绝保存并返回 False。"""
        clean = sanitize_tab_order(order)
        if clean is None:
            return False
        self._data["tab_order"] = clean
        self._data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        self._save()
        return True
