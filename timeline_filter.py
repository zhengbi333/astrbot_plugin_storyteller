"""时间线事件的可注入性判定（供所有「上下文注入 LLM」的路径共用）。

设计要点（独立实现，不与外部插件雷同）：
- 记忆库时间线里存在两类「非对话」事件：记忆库操作（kind="op"，如「导出记忆档案 3 条」）
  与系统通知（is_system，退群/入群/撤回等状态标记）——它们不是用户与 Bot 的对话，
  不应作为 LLM 上下文；
- 页面展示（记忆页时间线）仍显示全部事件（用户可见），仅注入路径过滤。
"""

from __future__ import annotations

from typing import Any


def is_llm_context_event(ev: Any) -> bool:
    """判断时间线事件是否可作为「对话上下文」注入 LLM。

    False = 记忆库操作（op）或系统通知（is_system），注入路径应跳过。
    """
    try:
        if isinstance(ev, dict):
            if str(ev.get("kind") or "") == "op":
                return False
            return not bool(ev.get("is_system"))
        return not (
            str(getattr(ev, "kind", "") or "") == "op"
            or bool(getattr(ev, "is_system", False))
        )
    except Exception:
        return False
