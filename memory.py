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
    # 0.191：显式「记住/记一下」类话术补齐（此前只有「记得」，用户说「你记住xxx」检测不到）
    "记住", "记一下", "记下来", "记着", "帮我记", "记忆一下", "存一下", "存下来", "记录下来",
)

PROFILE_HINTS = (
    "我喜欢", "我讨厌", "我不喜欢", "我最", "我习惯", "我一般", "我平时",
    "我超", "我特别", "我不吃", "我吃", "我住", "我是", "我在",
)

# 0.191：显式「记住/约定」消息的轻量分类（LLM 提炼失败时的兜底，也可直接用于弱模型场景）
# 三档：强约定词 > 偏好词 > 弱约定词（避免「别忘了我爱吃辣」被误归为约定）
REMEMBER_PROMISE_STRONG = ("约定", "说好", "答应", "约好", "说好了", "我们约", "答应我", "承诺")
REMEMBER_PREF_KW = ("我喜欢", "我讨厌", "我不喜欢", "我最", "我习惯", "我平时", "我爱吃", "爱喝", "我不吃", "我不爱")
REMEMBER_PROMISE_WEAK = ("以后", "下次", "别忘了", "一定要", "改天", "回头", "有空")


def classify_remember(text: str) -> str:
    """轻量分类：强约定/承诺 → promise；偏好 → preference；弱约定/其他 → promise / fact。"""
    t = (text or "").strip()
    if any(k in t for k in REMEMBER_PROMISE_STRONG):
        return "promise"
    if any(k in t for k in REMEMBER_PREF_KW):
        return "preference"
    if any(k in t for k in REMEMBER_PROMISE_WEAK):
        return "promise"
    return "fact"


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
    """构造「从消息提炼记忆/约定/偏好」的提示词（0.191：输出 JSON 带类型）。"""
    return (
        "判断下面这条用户消息里，是否包含对方要求你一直记住的内容："
        "比如「记住/记一下 xxx」「我们约定/说好 xxx」「别忘了 xxx」「以后想一起/下次 xxx」、"
        "或明显希望你长期记住的事实、偏好。\n"
        "如果有，只输出一行 JSON：{\"content\": \"精简的中文记忆内容（第三人称、带双方称呼，"
        "不含「用户/机器人」通称）\", \"memory_type\": \"promise|preference|fact|note\"}——"
        "约定/承诺用 promise，偏好用 preference，单纯事实用 fact，备注用 note。\n"
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
