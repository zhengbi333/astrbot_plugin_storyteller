"""拟人化重写：把各锚统一组装进请求，可选润色用户消息。

设计要点（独立实现，不与外部插件雷同）：
- 组装：把身份锚、风格锚、状态锚、日程锚按稳定顺序前置到 system_prompt；
- 润色：可选地调用 LLM 把用户消息轻量润色成更自然的表述（不改变原意）；
- 记忆注入仍由【为你篆刻的历史】插件桥接完成，本模块只负责「说话相关的锚」。
"""

from __future__ import annotations

from typing import Any


def assemble_request(
    req: Any,
    *,
    identity: str = "",
    voice: str = "",
    presence: str = "",
    schedule: str = "",
    relationship: str = "",
) -> None:
    """把各锚前置到 system_prompt 稳定区（marker 防重复注入）。"""
    anchors = [
        ("identity", identity),
        ("relationship", relationship),
        ("voice", voice),
        ("presence", presence),
        ("schedule", schedule),
    ]
    for key, text in anchors:
        if not text or not str(text).strip():
            continue
        marker = f"<!-- storyteller_{key}_anchor_v1 -->"
        current = str(getattr(req, "system_prompt", "") or "")
        if marker in current:
            continue
        if current:
            req.system_prompt = f"{marker}\n{text}\n\n{current}".strip()
        else:
            req.system_prompt = f"{marker}\n{text}"


def build_rewrite_prompt(user_text: str, voice_desc: str) -> str:
    """构造「轻量润色用户消息」的提示词。"""
    return (
        "把下面这条用户消息轻量润色成更自然的说法。只输出润色后的文本，"
        "不要任何解释、引号或标记。保持原意、语气和信息不变，不要增删事实，"
        "只是让表达更口语、更自然；如果已经足够自然，就原样输出。\n\n"
        + (f"参考说话风格：{voice_desc}\n\n" if voice_desc else "")
        + f"用户消息：{user_text.strip()}"
    )


async def rewrite_user_message(provider: Any, user_text: str, voice_desc: str = "") -> str:
    """调用 LLM 润色用户消息；失败时原样返回。"""
    if provider is None or not user_text or not user_text.strip():
        return user_text or ""
    try:
        from .models import chat_text

        resp = await chat_text(
            provider,
            None,
            prompt=build_rewrite_prompt(user_text, voice_desc),
            session_id="storyteller_rewrite",
            _disable_thinking=False,  # 创作类润色：保留模型思考
        )
        result = str(getattr(resp, "completion_text", "") or "").strip()
        return result or user_text
    except Exception:
        return user_text
