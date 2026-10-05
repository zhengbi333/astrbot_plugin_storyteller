"""智能沉默：判定「这条回复该不该发 / 该不该只草草回一句」。

0.234 起从「回复链路」（pipeline）独立成模块，面板单开「沉默」页（紧随「拦＆改」）。

本模块只做三件事（判定本身仍由 reply_pipeline 直连判定模型执行）：
  1) **配置读取**：新键 `silence.*` 优先；未显式配置时回退旧键 `pipeline.*`，
     保证升级后历史配置不丢（用户改过一次的值不会被默认值顶掉）；
  2) **判定上下文**：把「此刻时间 + 她此刻在做什么（是否在睡）」交给判定模型——
     否则模型看不到日程，就永远判不出「这会儿她在睡，可以不回」；
  3) **规则文案**：silence / brief / send 的判定口径（含深夜睡觉可沉默、brief 不得用来"回短一点"）。

计数（连续沉默上限）与留档（没说出口的心里话）仍在 main.py 内完成。
"""

from __future__ import annotations

import time
import re
from typing import Any

# 新模块的键 → 旧键（按优先级排列，用于兼容升级前的配置）
_LEGACY: dict[str, tuple[str, ...]] = {
    "enabled": ("pipeline.takeover_judge_enabled", "pipeline.judge_enabled"),
    "provider_id": ("pipeline.provider_id",),
    "silence_streak_limit": ("pipeline.silence_streak_limit",),
    "brief_enabled": (),
    "context_enabled": (),
    "night_silence": (),
}

_DAY_PARTS: tuple[tuple[int, int, str], ...] = (
    (0, 5, "凌晨"),
    (5, 8, "清晨"),
    (8, 12, "上午"),
    (12, 14, "中午"),
    (14, 18, "下午"),
    (18, 20, "傍晚"),
    (20, 23, "晚上"),
    (23, 24, "深夜"),
)

_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 日程里出现这些字眼 → 认为她此刻在睡
_SLEEP_WORDS = ("睡", "入梦", "就寝", "梦乡")


def _explicit(config: Any, dotted: str) -> Any:
    """取**显式**配置值；未配置（或为 None）时返回 None —— 用于区分"改过"和"没改过"。"""
    try:
        return config.get(dotted, None)
    except Exception:
        return None


def _resolve(config: Any, key: str) -> Any:
    """新键显式值优先，其次按 `_LEGACY` 顺序回退旧键；都没有返回 None。"""
    value = _explicit(config, f"silence.{key}")
    if value is not None:
        return value
    for legacy in _LEGACY.get(key, ()):
        value = _explicit(config, legacy)
        if value is not None:
            return value
    return None


def _as_bool(value: Any, default: bool) -> bool:
    """与 ConfigView.bool 口径一致的布尔转换（含中英文真值字符串）。"""
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "开", "开启"}
    return bool(value)


def enabled(config: Any) -> bool:
    """智能沉默总开关。未配置新键时沿用旧的判定开关，避免升级后行为突变。"""
    return _as_bool(_resolve(config, "enabled"), True)


def provider_id(config: Any) -> str:
    """判定模型（新键 → 旧键；不含表情包名额）。留空由「留空回退模型」策略兜底。"""
    return str(_resolve(config, "provider_id") or "").strip()


def streak_limit(config: Any) -> int:
    """连续沉默上限（0 = 永不主动沉默）。范围钳制 0~10。"""
    value = _resolve(config, "silence_streak_limit")
    try:
        number = int(value) if value is not None else 2
    except Exception:
        number = 2
    return max(0, min(10, number))


def brief_enabled(config: Any) -> bool:
    """是否允许「草草回复」（brief）。"""
    return _as_bool(_resolve(config, "brief_enabled"), True)


def context_enabled(config: Any) -> bool:
    """判定时是否附带「此刻时间 + 日程」。"""
    return _as_bool(_resolve(config, "context_enabled"), True)


def night_silence(config: Any) -> bool:
    """睡觉/深夜是否可作为沉默理由。"""
    return _as_bool(_resolve(config, "night_silence"), True)


def day_part(hhmm: str) -> str:
    """时段中文名（凌晨/清晨/上午/中午/下午/傍晚/晚上/深夜）。"""
    try:
        hour = int(str(hhmm).split(":")[0])
    except Exception:
        return ""
    for start, end, name in _DAY_PARTS:
        if start <= hour < end:
            return name
    return ""


def _schedule_facts(plugin: Any) -> tuple[str, bool]:
    """返回 (此刻在做什么, 是否可能在睡)。读不到就返回 ("", False)。"""
    try:
        from .schedule import current_activity, is_stale

        if not plugin.config.bool("schedule.enabled", True):
            return "", False
        store = getattr(plugin, "schedule_store", None)
        if store is None:
            return "", False
        schedule = store.load()
        if not isinstance(schedule, dict) or not schedule:
            return "", False
        if is_stale(schedule, time.strftime("%Y-%m-%d")):
            return "", False
        activity = str(current_activity(schedule, time.strftime("%H:%M")) or "").strip()
        if not activity:
            return "", False
        sleeping = any(word in activity for word in _SLEEP_WORDS)
        if re.search(r"睡不着|不(?:想|能|要|会)?睡|还没睡|尚未入睡|起床|醒来", activity):
            sleeping = False
        return activity, sleeping
    except Exception:
        return "", False


def build_context_block(plugin: Any, config: Any) -> str:
    """判定提示词用的「当前情境」段：此刻时间 + 她此刻在做什么 / 是否在睡。

    关闭 `silence.context_enabled` 时返回空串（判定模型只看得到状态锚）。
    """
    if not context_enabled(config):
        return ""
    local = time.localtime()
    hhmm = time.strftime("%H:%M", local)
    lines = [
        f"此刻时间：{time.strftime('%Y-%m-%d', local)} {hhmm}"
        f"（{_WEEKDAYS[local.tm_wday]}，{day_part(hhmm)}）"
    ]
    activity, sleeping = _schedule_facts(plugin)
    if activity:
        lines.append(f"她此刻按日程正在：{activity}")
        lines.append(f"她现在是否在睡觉：{'是' if sleeping else '否'}")
    return "\n".join(lines)


def build_rules_text(*, brief_enabled: bool = True, night_silence: bool = True) -> str:
    """判定规则文案（silence / brief / send 的口径）。"""
    silence_rule = (
        "- action 为 silence：这条消息不值得回。典型情形：用户只是「嗯/哦/好/行/知道了」这类敷衍收尾、"
        "话题已经自然结束、或此刻沉默更自然。不要把一句短消息直接当作敷衍："
        "若它在确认仍未处理的问题、表达求助或继续前一话题，应正常回应"
    )
    if night_silence:
        silence_rule += (
            "；若她正在睡觉，或状态明显是深夜困倦，而对方只是「在吗/在么/嗯」这类没有实质内容的搭话，"
            "可以判 silence；这是允许沉默的情境，不是强制规则。"
            "有明确问题、求助、紧急情况或此前尚未回应的请求时，应优先正常回应，"
            "不能仅凭「在吗」两个字忽略其后附带的信息"
        )
    silence_rule += "，text 用空字符串；"

    lines = ["规则：", silence_rule]
    if brief_enabled:
        lines.append(
            "- action 为 brief：仅当她「无语 / 困惑 / 大脑短路」时使用，text 只填「？」「…？」「啊？」"
            "这类一两个字的反应；不要用它表达「想回短一点」——想简短请在 action=send 的 text 里写短句，"
            "brief 会丢弃已经写好的回复内容；"
        )
    lines.append("- action 为 send：正常回复，text 是最终发送的完整文本；")
    return "\n".join(lines)


def apply_decision(plugin: Any, event: Any, judged: Any, original: str) -> dict:
    """统一主链和接管的沉默限额；模型失败、工具完成或关闭时保持正常回复。"""
    session_id = str(getattr(event, "unified_msg_origin", "") or "")
    streaks = getattr(plugin, "_silence_streak", None)
    if not isinstance(streaks, dict):
        streaks = plugin._silence_streak = {}
    from .capabilities import caps_done

    if not enabled(plugin.config) or caps_done(event) or not isinstance(judged, dict):
        if session_id:
            streaks[session_id] = 0
        return {"action": "send", "text": original}
    result = dict(judged)
    action = str(result.get("action") or "send").strip().lower()
    if action == "silence" and session_id:
        limit = streak_limit(plugin.config)
        streak = max(0, int(streaks.get(session_id, 0) or 0))
        if streak < limit:
            streaks[session_id] = streak + 1
            # 0.238：沉默计数落盘，重启后"连续沉默上限"的保护不丢
            try:
                plugin._mark_runtime_dirty()
            except Exception:
                pass
            result.update(action="silence", text="")
            return result
        result["forced_reply"] = True
    if session_id:
        streaks[session_id] = 0
    text = str(result.get("text") or "").strip()
    if action == "brief" and brief_enabled(plugin.config) and text and len(text) <= 20:
        result.update(action="brief", text=text)
    elif action == "send":
        result.update(action="send", text=text or original)
    else:
        result.update(action="send", text=original)
    return result
