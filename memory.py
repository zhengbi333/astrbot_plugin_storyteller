"""记忆写入：把用户画像、约定/愿望写入记忆插件（为你篆刻的历史）。

设计要点（独立实现，不与外部插件雷同）：
- 通过记忆插件的桥接接口写入，源插件标记为本插件；
- 约定/愿望先用轻量规则检测候选，再由 LLM 提炼成一条记忆写入；
- 用户画像从最近对话提炼，定期写入（不逐句写，避免噪音）。
"""

from __future__ import annotations

from typing import Any

from .persona import extract_sender

SOURCE_PLUGIN = "astrbot_plugin_storyteller"

COMMITMENT_HINTS = (
    "约定", "说好", "答应", "以后", "下次", "改天", "回头", "有空",
    "想要", "想一起", "一起去", "记得", "别忘了", "一定要",
)

PROFILE_HINTS = (
    "我喜欢", "我讨厌", "我不喜欢", "我最", "我习惯", "我一般", "我平时",
    "我超", "我特别", "我不吃", "我吃", "我住", "我是", "我在",
)


def build_session_context(event: Any) -> dict[str, str]:
    """从事件构建记忆插件需要的会话上下文。"""
    sender = extract_sender(event)
    session_id = sender.get("session_id") or ""
    platform = session_id.split(":", 1)[0] if ":" in session_id else ""
    low = session_id.lower()
    if ":groupmessage:" in low or ":group:" in low:
        scope = "group"
    elif (
        ":friendmessage:" in low
        or ":privatemessage:" in low
        or ":friend:" in low
        or ":private:" in low
    ):
        scope = "private"
    else:
        scope = "unknown"
    return {
        "session_id": session_id,
        "scope": scope,
        "platform": platform,
        "user_id": sender.get("user_id") or "",
        "user_name": sender.get("user_name") or "",
    }


def detect_commitment(text: str) -> bool:
    """轻量检测：消息里是否可能包含约定/愿望（供后续 LLM 确认）。"""
    clean = (text or "").strip()
    if len(clean) < 4 or len(clean) > 200:
        return False
    return any(hint in clean for hint in COMMITMENT_HINTS)


def detect_profile(text: str) -> bool:
    """轻量检测：消息里是否可能包含稳定偏好/画像信息。"""
    clean = (text or "").strip()
    if len(clean) < 4 or len(clean) > 200:
        return False
    return any(hint in clean for hint in PROFILE_HINTS)


async def write_memory(
    bridge: Any,
    *,
    content: str,
    memory_type: str,
    event: Any,
    importance: float | None = None,
) -> str:
    """写入一条记忆，返回 memory_id（失败返回空串）。"""
    if bridge is None or not content or not content.strip():
        return ""
    try:
        adder = getattr(bridge, "add_memory", None)
        if not callable(adder):
            return ""
        return await adder(
            content=content.strip(),
            memory_type=memory_type,
            session_context=build_session_context(event),
            importance=importance,
            source_plugin=SOURCE_PLUGIN,
        )
    except Exception:
        return ""


def build_commitment_prompt(text: str) -> str:
    """构造「从消息提炼约定/愿望」的提示词。"""
    return (
        "判断下面这条用户消息是否包含一条值得记住的约定、愿望或承诺。"
        "如果有，只输出一条精简的中文记忆内容（用第三人称、带双方称呼，不含「用户/机器人」通称）；"
        "如果没有，只输出空字符串。不要任何解释或标记。\n\n"
        f"用户消息：{text.strip()}"
    )


def build_profile_prompt(recent_texts: list[str], existing: list[str] | None = None) -> str:
    """构造「从最近对话提炼用户画像」的提示词。

    existing 为已有画像，用于避免重复、只输出新增或更新的信息。
    """
    joined = "\n".join(f"- {t.strip()}" for t in (recent_texts or []) if t and t.strip())
    lines = [
        "从下面这些最近的用户发言里，提炼 1~3 条稳定的用户画像信息"
        "（偏好、习惯、身份、性格、关系等长期有效的），每条用一句精简中文。",
    ]
    if existing:
        lines.append("已有画像（不要重复这些，只输出新增或明显更新的）：")
        lines.extend(f"- {e}" for e in existing[:10])
    lines.append("只输出一个 JSON 数组，形如 [\"...\", \"...\"]，不要任何解释或代码块标记；没有可提炼的就输出 []。")
    lines.append(f"\n最近发言：\n{joined}")
    return "\n".join(lines)


def parse_profile_items(text: str) -> list[str]:
    """解析画像提炼返回的字符串列表（0.150：宽松容错）。"""
    if not text:
        return []
    from .json_util import parse_json_lenient

    value = parse_json_lenient(text)
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()][:3]
    return []
