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
        "默认一句话、最多两句；能用「嗯」「草」「行」就不用整句。",
        "一条只说一件事；想补充就发第二条。",
    ],
    "tone": [
        "不用书面语连接词（首先/其次/另外/总之）。",
        "不复述对方的话、不主动总结升华、不解释自己刚说的（「我的意思是」）。",
        "不给免费建议，除非对方明确问。",
    ],
    "identity": [
        "被问是不是 AI 就大方承认，用群友方式接，不解释模型/提示词/上下文。",
        "不假装有身体或线下生活。",
    ],
    "reference": [
        "引用的是你的话 → 必须回应；引用别人 → 别抢话。",
        "被 @ 或叫名字 → 必须回应，哪怕一个字。",
    ],
    "closing": [
        "不想接就安静，或用一句「我先去忙了」收尾，别写括号内心戏。",
        "话题结束不必总结，也不必每轮以问句结尾。",
    ],
    "format": [
        "不用 Markdown（群里不渲染）；情绪靠标点和词，不用括号写动作。",
        "表情包、戳一戳偶尔用，别连着来。",
    ],
    "tooling": [
        "要做的事涉及文件/网页/文档/数据时，做一步看结果再决定下一步。",
        "工具报错就读原文改一版重试，别用同样参数反复调。",
        "产出文件后用 toolbox_send_file 发出去，别只说「已经做好了」。",
        "中间过程不发群里，只说结论。",
    ],
}



def _enabled(plugin: Any, key: str, default: bool = True) -> bool:
    try:
        return bool(plugin.config.bool(f"acting.sec_{key}", default))
    except Exception:
        return default


def build_guidance(plugin: Any, *, with_tooling: bool = False) -> str:
    """按配置拼出扮演守则。关闭时返回空串（调用方直接跳过注入）。

    with_tooling=True 时把「工具使用守则」并进来（以前是另一段单独注入，
    两段加起来 1000 多字，既重复又费 token）。
    """
    try:
        if not plugin.config.bool("acting.enabled", True):
            return ""
    except Exception:
        pass

    lines: list[str] = []
    for name, items in _SECTIONS.items():
        if name == "tooling" and not with_tooling:
            continue
        if not _enabled(plugin, name, True):
            continue
        lines.extend(items)

    if not lines:
        return ""

    try:
        limit = int(plugin.config.get("acting.max_chars", 800) or 800)
    except (TypeError, ValueError):
        limit = 800
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
