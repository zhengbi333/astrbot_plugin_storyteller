"""上下文预算：对话太长时，把**较早的消息压成摘要**，而不是直接丢弃。

为什么需要（以及为什么记忆插件替代不了它）：
- 记忆插件管的是"跨会话记得住"——它把**检索到的**片段注入 system；
- 上下文预算管的是"**这次对话**别把窗口撑爆"——它处理的是 `req.contexts` 里已经积累的消息。

两者方向相反：记忆是"往 prompt 里加"，预算是"从历史里减"。只有记忆没有预算，
长对话照样会超窗、照样会被模型丢掉最重要的近期内容。

策略（保守，可解释）：
1. 估算 system + contexts + 当前 prompt 的总字数；
2. 没超预算 → 原样返回，**一个字都不动**；
3. 超了 → 保留最近 `keep_recent` 条原始消息，更早的每条取前 `summary_chars` 字，
   合成**一条** system 消息放在最前面（明确标注是压缩过的）；
4. 还超 → 逐步缩小保留条数（最少 4 条），最后把摘要行也截断。

不做的事：不改写消息内容、不动角色、不删当前用户消息。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

MAX_TOTAL_CHARS = 14000
KEEP_RECENT = 8
SUMMARY_CHARS = 80
MIN_KEEP = 4


@dataclass(slots=True)
class BudgetResult:
    contexts: list[dict]
    compacted: int
    before_chars: int
    after_chars: int
    note: str = ""

    @property
    def changed(self) -> bool:
        return self.compacted > 0


def _text_of(message: object) -> str:
    """取一条消息的文本（兼容 str 与 OpenAI 的 content 数组）。"""
    if not isinstance(message, dict):
        return str(message or "")
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content or "")


def estimate_chars(*, system: str = "", contexts: list[dict] | None = None, prompt: str = "") -> int:
    total = len(str(system or "")) + len(str(prompt or ""))
    for message in contexts or []:
        total += len(_text_of(message))
    return total


def _brief(message: dict, limit: int) -> str:
    role = str(message.get("role") or "?")
    text = " ".join(_text_of(message).split())
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    label = {"user": "对方", "assistant": "我", "system": "系统", "tool": "工具"}.get(role, role)
    return f"{label}：{text}" if text else ""


def compress_contexts(
    contexts: list[dict] | None,
    *,
    system: str = "",
    prompt: str = "",
    max_chars: int = MAX_TOTAL_CHARS,
    keep_recent: int = KEEP_RECENT,
    summary_chars: int = SUMMARY_CHARS,
    min_keep: int = MIN_KEEP,
) -> BudgetResult:
    """按预算压缩历史消息。返回新的 contexts（不改入参）。"""
    items = list(contexts or [])
    before = estimate_chars(system=system, contexts=items, prompt=prompt)
    if before <= max_chars or len(items) <= min_keep:
        return BudgetResult(contexts=items, compacted=0, before_chars=before, after_chars=before)

    keep = max(min_keep, min(int(keep_recent), len(items)))
    while True:
        older = items[:-keep]
        recent = items[-keep:]
        lines = [line for line in (_brief(m, summary_chars) for m in older) if line]
        summary = "【更早的对话（已压缩）】\n" + "\n".join(lines) if lines else ""
        merged: list[dict] = []
        if summary:
            merged.append({"role": "system", "content": summary})
        merged.extend(recent)
        after = estimate_chars(system=system, contexts=merged, prompt=prompt)
        if after <= max_chars or keep <= min_keep:
            if after > max_chars and summary:
                # 最后手段：把摘要本身也截短
                allowance = max(200, max_chars - (after - len(summary)))
                merged[0] = {"role": "system", "content": summary[:allowance].rstrip() + "…（已截断）"}
                after = estimate_chars(system=system, contexts=merged, prompt=prompt)
            return BudgetResult(
                contexts=merged,
                compacted=len(older),
                before_chars=before,
                after_chars=after,
                note=f"压缩了 {len(older)} 条较早消息",
            )
        keep = max(min_keep, keep - 2)


def apply_to_request(req: object, *, max_chars: int = MAX_TOTAL_CHARS, keep_recent: int = KEEP_RECENT) -> BudgetResult:
    """直接就地压缩一个 ProviderRequest（改 req.contexts）。失败不影响主流程。"""
    try:
        contexts = list(getattr(req, "contexts", None) or [])
        system = str(getattr(req, "system_prompt", "") or "")
        prompt = str(getattr(req, "prompt", "") or "")
        result = compress_contexts(
            contexts, system=system, prompt=prompt,
            max_chars=max_chars, keep_recent=keep_recent,
        )
        if result.changed:
            req.contexts = result.contexts
        return result
    except Exception as exc:  # 预算是"优化"，不该让主流程挂掉
        return BudgetResult(contexts=[], compacted=0, before_chars=0, after_chars=0,
                            note=f"压缩失败（已跳过）：{type(exc).__name__}")


def describe(result: BudgetResult) -> str:
    if not result.changed:
        return f"未超预算（{result.before_chars} 字），未改动"
    return (
        f"{result.before_chars} → {result.after_chars} 字，"
        f"压缩 {result.compacted} 条较早消息"
    )


def summarize_messages(messages: list[dict], *, summary_chars: int = SUMMARY_CHARS) -> str:
    """把一批消息压成一段摘要文本（供接管链路自己拼 prompt 时使用）。"""
    lines = [line for line in (_brief(m, summary_chars) for m in messages) if line]
    return "\n".join(lines)
