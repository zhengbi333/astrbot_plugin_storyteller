"""思绪（内心持久化）：让模型"没说出口的那半句"落盘，并在下一轮成为它自己继续想的起点。

设计（实测依据见 `内心持久化与工具扩展方案.md`）：
- **产出**：在 system 尾部追加一段指令，要求模型在回复末尾用隐藏块写下此刻没说出口的思绪
  （实测：真实 DeepSeek 遵守率 95%、未闭合泄漏 0/20、延迟与不加完全相同——同一次生成，无额外调用）。
- **剥离**：生成后**立即**把隐藏块从可见文本里摘掉。这段内容绝不进入润色 / 表情包 / 发送链路，
  也不会被发给对方（发送前还有一道保险）。
- **留档**：摘出的内容存进 `MindStore.inner`（最新在前），带时间 / 会话 / 对方那句 / 可见回复 / 心情快照。
- **回注**：下一轮把**最近 N 条同会话**的思绪作为"你上一轮没说出口的那半句"注入 system，
  带单条字数截断、已注入去重（避免反复咀嚼同一件事）、可一键关。

**独立性声明（避免与任何外部插件雷同）**：本模块只处理「对话轮次内的思绪连续性」——
产出方式（回复内隐藏块 + 生成后剥离）、数据结构（时间/会话/对方话/可见回复/思绪/心情）、
回注策略（同会话最近 N 条 + 去重 + 截断）与配置键（`mindstream.*`）均为本插件自有设计；
与外部插件的"主动消息候选池 / 内心活动风格配置 / 日记文体"等机制在目的、载体与数据上均不相同。

为什么不用模型自带的 reasoning：本机模型（deepseek-v4-flash-vision-exp）开关思考都**不返回**
`reasoning_content`（实测 0 字，开思考还让延迟涨到 3.72 倍），且 reasoning 是"解题思路"，
不如角色自己的口吻贴合人设。
"""

from __future__ import annotations

import re
from typing import Any

OPEN_TAG = "<思绪>"
CLOSE_TAG = "</思绪>"

# 闭合块（正常情况）
INNER_CLOSED = re.compile(r"<思绪>(.*?)</思绪>", re.S)
# 未闭合兜底：出现开标签但没闭合 → 吃到文末（模型漏写闭合时的保险）
INNER_UNCLOSED = re.compile(r"<思绪>(.*)$", re.S)
# 任何残留标签（用于判定"可见部分是否被污染"）
ANY_TAG = re.compile(r"</?思绪>")

DEFAULT_KEEP = 30
DEFAULT_INJECT = 1
DEFAULT_MAX_CHARS = 120


def _cfg(plugin: Any, key: str, default: Any) -> Any:
    try:
        return plugin.config.get(f"mindstream.{key}", default)
    except Exception:
        try:
            return plugin.config.get(key, default)
        except Exception:
            return default


def enabled(plugin: Any) -> bool:
    """思绪总开关（独立功能独立开关，默认开）。"""
    try:
        return bool(plugin.config.bool("mindstream.enabled", True))
    except Exception:
        return False


def keep_limit(plugin: Any) -> int:
    try:
        return max(1, min(200, int(plugin.config.int("mindstream.keep", DEFAULT_KEEP) or DEFAULT_KEEP)))
    except Exception:
        return DEFAULT_KEEP


def inject_count(plugin: Any) -> int:
    try:
        return max(0, min(5, int(plugin.config.int("mindstream.inject_count", DEFAULT_INJECT) or 0)))
    except Exception:
        return DEFAULT_INJECT


def inject_max_chars(plugin: Any) -> int:
    try:
        return max(20, min(500, int(plugin.config.int("mindstream.inject_max_chars", DEFAULT_MAX_CHARS) or DEFAULT_MAX_CHARS)))
    except Exception:
        return DEFAULT_MAX_CHARS


def strip_unclosed_enabled(plugin: Any) -> bool:
    try:
        return bool(plugin.config.bool("mindstream.strip_unclosed", True))
    except Exception:
        return True


# ---------------------------------------------------------------- 生成指令

def build_instruction(plugin: Any) -> str:
    """system 尾部追加的"写下思绪"指令；关闭时返回空串。"""
    if not enabled(plugin):
        return ""
    return (
        "\n\n【藏起来的那半句】每轮回复的最后，都另起一行用一个隐藏块写下你此刻**没说出口的思绪**"
        f"（对方看不到它，但会记进你心里，成为你下一轮继续想下去的起点）。格式：\n"
        f"{OPEN_TAG}一到两句、第一人称、口语，写你真正的想法（在意、疑惑、忍住没说出口的话都可以）{CLOSE_TAG}\n"
        "每轮都写——哪怕只有很短一句，也别把这一轮留空（连着几轮不写，你心里就接不上了）。"
        "只有这个块是藏起来的，块外的文字才是你说出口的话；不要解释这个块、也不要提到它。"
    )


# ---------------------------------------------------------------- 剥离

def split_inner(plugin: Any, text: str) -> tuple[str, str]:
    """把回复切成（可见文本, 内心文本）。内心为空表示这轮没写（实测约 5%）。

    - 正常闭合：取块内内容，块从可见文本移除；
    - 未闭合（模型漏写闭合标签）且开关开启：吃到文末，同样从可见文本移除（保险）；
    - 可见文本里若仍残留标签字样，再清一次，避免任何标记被发出去。
    """
    raw = str(text or "")
    if not raw:
        return "", ""
    inner = ""
    visible = raw
    m = INNER_CLOSED.search(raw)
    if m:
        inner = str(m.group(1) or "").strip()
        visible = INNER_CLOSED.sub(" ", raw)
    else:
        m2 = INNER_UNCLOSED.search(raw)
        if m2 and strip_unclosed_enabled(plugin):
            inner = str(m2.group(1) or "").strip()
            visible = raw[: m2.start()]
    visible = ANY_TAG.sub(" ", visible)
    visible = re.sub(r"[ \t]{2,}", " ", visible)
    visible = re.sub(r"\n{3,}", "\n\n", visible).strip()
    return visible, inner


def looks_polluted(text: str) -> bool:
    """可见文本里是否残留内心标记（用于兜底判定）。"""
    return bool(ANY_TAG.search(str(text or "")))


# ---------------------------------------------------------------- 选条与回注

def pick_for_injection(
    items: list[dict[str, Any]],
    *,
    session: str,
    count: int,
    already: set[str] | None = None,
) -> list[dict[str, Any]]:
    """挑要回注的思绪：同会话优先、最新的在前、跳过已注入过的 id、最多 count 条。"""
    if count <= 0:
        return []
    used = {str(x) for x in (already or set())}
    out: list[dict[str, Any]] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        if session and str(it.get("session") or "") and str(it.get("session")) != str(session):
            continue  # 跨会话不串（别把群里的心事带进私聊）
        iid = str(it.get("id") or "")
        if iid and iid in used:
            continue
        if not str(it.get("inner") or "").strip():
            continue
        out.append(it)
        if len(out) >= count:
            break
    return out


def render_injection(plugin: Any, picked: list[dict[str, Any]]) -> str:
    """把挑中的思绪渲染成 system 注入段（用词与其他模块一致，避免与外部插件的措辞相撞）。"""
    if not picked:
        return ""
    limit = inject_max_chars(plugin)
    lines = ["【你上一轮的思绪】（你当时没说出口的那半句；可以自然延续，也可以不提，别复述它）"]
    for it in picked:
        text = str(it.get("inner") or "").strip()
        if len(text) > limit:
            text = text[:limit] + "…"
        at = str(it.get("at") or "")[-5:]
        if at:
            lines.append(f"- （{at}）{text}")
        else:
            lines.append(f"- {text}")
    return "\n".join(lines)
