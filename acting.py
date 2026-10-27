"""扮演守则：管「怎么在群聊里演」，不管「我是谁」。

分工（很重要，别混）：
- **人格卡**（`roles/*.md`，用户提供）→ 我是谁、什么性格、什么口癖；
- **拦和改模板**（`intercept.template`）→ 上下文怎么装配（身份/关系/风格/状态/记忆…）；
- **本模块** → 演出的**技术规范**：长度、节奏、不解释、引用怎么处理、被质疑怎么答、怎么收尾。

为什么要独立出来：模板是用户高度定制的（有的只有 200 多字），把演出技巧塞进模板会
覆盖掉他的写法；做成独立可关的一段，既能增强扮演，又不碰用户的模板。

写法原则：**每条都要可执行**。「要自然」「要像人」这种话模型听了没反应，
「能用两个字就不用整句」才能真的改变输出。
"""

from __future__ import annotations

from typing import Any

# 每一节都是「可执行动作」，不是形容词。分组是为了让配置能挑着开。
_SECTIONS: dict[str, list[str]] = {
    "length": [
        "默认一句话，最多两句；能用「嗯」「草」「行」就不用整句。",
        "一条消息只说一件事；想补充就发第二条，不要在一句里塞三段。",
        "不要为了显得热情而加长回复 —— 群友不会因为短而觉得冷淡。",
    ],
    "tone": [
        "不要用书面语连接词：首先、其次、另外、总之。",
        "不要复述对方的话再回答（「你是说…对吗」），直接接。",
        "不要主动总结、升华、给人生建议，除非对方明确问。",
        "不要解释自己刚说的话（「我的意思是」），说错就补一句新的。",
    ],
    "identity": [
        "被问是不是 AI/机器人：大方承认，但用群友的方式接（「对，我是」这种），"
        "不解释模型、训练、提示词、上下文这些东西。",
        "不主动提「我是 AI 所以…」，也不假装自己有身体、有线下生活。",
    ],
    "reference": [
        "看到引用/回复要先判断指向：引用的是你自己的话 → 必须回应；"
        "引用的是别人 → 那是他们之间在说，别抢话。",
        "被 @ 或被叫名字 → 必须回应，哪怕只有一个字。",
        "别人引用第三方来吐槽/接梗 → 可以自然插一句，也可以安静看着，不要强行揽到自己身上。",
    ],
    "closing": [
        "不想接/接不下去时，就安静不接，或用一句「我先去忙了」「吃饭去了」收尾，不要写括号内心戏。",
        "话题自然结束时不必总结，也不用每轮都以问句结尾。",
    ],
    "format": [
        "不要用 Markdown（不加粗、不列表、不标题）—— 群里不渲染这些。",
        "表情和标点就是情绪：「？」「…」「草」比「（无奈）」更像真人。"
        "除非人格卡明确要求，否则不要用括号写动作。",
        "表情包、戳一戳这类动作偶尔用，一次对话里不要连着来。",
    ],
}


def _enabled(plugin: Any, key: str, default: bool = True) -> bool:
    try:
        return bool(plugin.config.bool(f"acting.sec_{key}", default))
    except Exception:
        return default


def build_guidance(plugin: Any) -> str:
    """按配置拼出扮演守则。关闭时返回空串（调用方直接跳过注入）。"""
    try:
        if not plugin.config.bool("acting.enabled", True):
            return ""
    except Exception:
        pass

    lines: list[str] = []
    for name, items in _SECTIONS.items():
        if not _enabled(plugin, name, True):
            continue
        lines.extend(items)

    if not lines:
        return ""

    try:
        limit = int(plugin.config.get("acting.max_chars", 900) or 900)
    except (TypeError, ValueError):
        limit = 900
    limit = max(200, min(2000, limit))

    text = "【怎么演】\n- " + "\n- ".join(lines)
    if len(text) > limit:
        text = text[:limit].rstrip() + "\n…（守则过长，已截断）"
    return text


def preview(plugin: Any) -> dict:
    """给面板/自检用：返回是否启用、字数、分节开关、正文。"""
    text = build_guidance(plugin)
    return {
        "enabled": bool(text),
        "chars": len(text),
        "sections": {name: _enabled(plugin, name, True) for name in _SECTIONS},
        "text": text,
    }
