"""回复链路：主链回复的二次润色 + 智能判定 + 表情包占位符渲染。

设计目标（独立实现，只借「二次处理」思路，不复刻示例代码）：
- 润色与判定都有明确的输入上下文与精细约束，失败时逐级安全回退，绝不因链路出错而吞掉回复；
- 判定覆盖「沉默 / 草草回复 / 表情包 / 正常发送」四类，并给出表情包的位置与分类依据；
- 表情包以占位符留在文本里，由渲染阶段替换成真实图片。
"""

from __future__ import annotations

import json
import re
from typing import Any

from .log import logger
from .models import chat_text, resolve_chat_provider

EMOJI_PATTERN = re.compile(r"\[EMOJI:([^\]]+)\]")

# 草草回复的候选短语（判定模型可复用，也作为解析兜底）
BRIEF_CANDIDATES = ("?", "？", "...", "…", "...?", "…？", "...啊?", "…啊？", "诶？", "啊？")


def _usage_of(resp: Any) -> tuple[int, int]:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return 0, 0
    inp = int(getattr(usage, "input_other", 0) or 0) + int(getattr(usage, "input_cached", 0) or 0)
    out = int(getattr(usage, "output", 0) or 0)
    return inp, out


def _voice_desc(voice: dict[str, Any]) -> str:
    parts = []
    if voice.get("tone"):
        parts.append(f"语气基调：{voice['tone']}")
    if voice.get("sentence_length"):
        parts.append(f"句子长短：{voice['sentence_length']}")
    if voice.get("address"):
        parts.append(f"称呼与距离感：{voice['address']}")
    if voice.get("rhythm"):
        parts.append(f"回复节奏：{voice['rhythm']}")
    return "；".join(parts)


def squeeze_reply(text: str) -> str:
    """0.186：回复文本拍平——去除换行/空行/连续空格（主链模型常输出 \n\n，QQ 端显示成大空隙）。"""
    t = str(text or "")
    t = re.sub(r"\n{2,}", "\n", t)
    t = re.sub(r"\s*\n\s*", " ", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


def build_rewrite_prompt(original: str, user_text: str, presence: str, profile: str, voice: str) -> str:
    """二次润色：保持原意，只调整「怎么说」。"""
    lines = [
        "下面是一条机器人准备回复用户的消息。请把它二次润色得更自然、更像真人说话。",
        "要求：",
        "1. 保持原意与信息量完全不变，不增删事实、不改变结论；",
        "2. 去掉机械感、翻译腔、冗余套话（如「作为AI」「希望对你有所帮助」「让我来…」）；",
        "3. 贴合下面的说话风格，让语气、措辞、节奏都像这个角色；",
        "4. 有温度、有分寸，不油腻、不讨好；",
        "5. 长度与原文相当，不要越写越长；",
        "6. 只输出一个连续的自然段落，不要换行、不要空行、不要任何动作/括号描述。",
        "只输出润色后的文本本身，不要任何解释、引号或标记。",
    ]
    if voice:
        lines.append(f"说话风格：{voice}")
    if presence:
        lines.append(f"机器人此刻的状态：{presence}")
    if profile:
        lines.append(f"和当前用户的画像/关系：{profile}")
    lines.append(f"用户消息：{user_text[:600]}")
    lines.append(f"机器人原始回复：{original[:1600]}")
    return "\n".join(lines)


def build_judge_prompt(rewritten: str, user_text: str, presence: str, categories: list[str]) -> str:
    """智能判定：沉默 / 草草回复 / 表情包 / 正常发送。"""
    cat_hint = "、".join(f"「{c}」" for c in categories) if categories else "（尚未配置任何分类）"
    lines = [
        "下面是机器人准备好的一条回复。请判断它最终应该怎么发出去，只输出一个 JSON 对象，不要任何解释或代码块标记，字段固定为：",
        '{"action": "silence|brief|send", "text": "最终文本", "emoji": [{"category": "分类标题", "position": "start|end"}]}',
        "",
        "规则：",
        "- action 为 silence：这条消息不值得回（例如用户只是「嗯/哦/好/行/知道了」这类敷衍收尾、话题已经自然结束、或此刻沉默更自然），text 用空字符串；",
        "- action 为 brief：只用极短的「？」「…？」「啊？」之类草草回应（例如对方说了让人无语、困惑、大脑短路的话），text 就填那一两个字的短句；",
        "- action 为 send：正常回复，text 是最终发送的完整文本；",
        "- 只有当情绪/状态确实需要表情包时，才在 emoji 里填：category 必须是下面可用分类之一，position 为 start（表情包在文字前）或 end（表情包在文字后），并同时在 text 对应位置插入占位符 [EMOJI:分类标题]；",
        f"- 可用表情包分类：{cat_hint}；不要用不存在的分类，不要每句都带表情，不要插错语境。",
    ]
    if presence:
        lines.append(f"机器人此刻的状态：{presence}")
    lines.append(f"用户消息：{user_text[:600]}")
    lines.append(f"机器人准备回复：{rewritten[:1400]}")
    return "\n".join(lines)


def parse_judge(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    from .json_util import parse_json_lenient

    value = parse_json_lenient(text)
    return value if isinstance(value, dict) else None


class ReplyPipeline:
    """主链回复的二次处理：润色 + 判定 + 占位符。"""

    def __init__(self, plugin: Any):
        self._plugin = plugin

    def _config(self) -> Any:
        return self._plugin.config

    def _record(self, task: str, model: str, resp: Any) -> None:
        store = getattr(self._plugin, "token_store", None)
        if store is None:
            return
        try:
            inp, out = _usage_of(resp)
            store.record(task=task, model=model, input_tokens=inp, output_tokens=out)
        except Exception:
            pass

    def _categories(self) -> list[str]:
        try:
            return [str(c.get("title") or "") for c in self._plugin.emoji_store.categories()]
        except Exception:
            return []

    def _presence_text(self) -> str:
        try:
            from .presence import build_presence_anchor

            return build_presence_anchor(self._plugin.presence_store.load())
        except Exception:
            return ""

    async def process(self, event: Any, resp: Any) -> str:
        """处理主链回复，返回最终 completion_text（可能含表情包占位符）。"""
        original = squeeze_reply(str(getattr(resp, "completion_text", "") or ""))
        if not original:
            return ""
        user_text = str(getattr(event, "message_str", "") or "").strip()
        presence = self._presence_text()
        relationship = self._relationship_text(event)
        voice = _voice_desc(self._plugin.voice_store.load())

        rewritten = await self._rewrite(event, original, user_text, presence, relationship, voice)
        if not rewritten:
            return original
        judged = await self._judge(rewritten, user_text, presence, relationship)
        if judged is None:
            return rewritten
        action = str(judged.get("action") or "send").strip()
        if action == "silence":
            logger.info("[Storyteller] 判定沉默，不回复: session=%s", getattr(event, "unified_msg_origin", ""))
            return ""
        if action == "brief":
            text = str(judged.get("text") or "").strip()
            return text if text else self._pick_brief()
        text = str(judged.get("text") or rewritten).strip()
        # 表情包发送策略：判定允许后 —— 用户 opt-out 则直接去掉；再按发送概率（含反馈权重）决定
        if text and EMOJI_PATTERN.search(text):
            import random

            user = ""
            try:
                from .persona import extract_sender

                user = extract_sender(event).get("user_id") or ""
            except Exception:
                pass
            store = getattr(self._plugin, "emoji_store", None)
            if store is not None:
                try:
                    if store.is_opt_out(user):
                        # 用户说过「别发表情包」：移除占位符，只发文字
                        text = EMOJI_PATTERN.sub("", text).strip()
                        logger.info("[Storyteller] 用户已表达不要表情包，跳过: session=%s",
                                     getattr(event, "unified_msg_origin", ""))
                        return text or rewritten
                except Exception:
                    pass
            prob = max(0.0, min(1.0, self._config().float("emoji.send_probability", 0.25)))
            if store is not None and user:
                # 按分类权重微调概率（反馈学习：升/降集）
                try:
                    weights = {}
                    for m in EMOJI_PATTERN.finditer(text):
                        cid_match = str(m.group(1) or "").strip()
                        if cid_match:
                            cid = getattr(store, "_title_to_id", lambda t: "")(cid_match) or ""
                            if cid:
                                weights[cid] = store.weight_for(user, cid)
                except Exception:
                    weights = {}
                if weights:
                    prob = max(0.0, min(1.0, prob * (sum(weights.values()) / len(weights))))
            if random.random() > prob:
                text = EMOJI_PATTERN.sub("", text).strip()
        return text or rewritten

    @staticmethod
    def _pick_brief() -> str:
        import random

        return random.choice(BRIEF_CANDIDATES)

    def _relationship_text(self, event: Any) -> str:
        """取当前用户的关系锚（决定语气亲密度）。"""
        try:
            from .persona import extract_sender
            from .relationship import build_relationship_anchor

            user_id = extract_sender(event).get("user_id") or ""
            if not user_id:
                return ""
            rel = self._plugin.relationship_store.get(user_id)
            return build_relationship_anchor(rel, self._plugin.presence_store.load())
        except Exception:
            return ""

    async def _rewrite(self, event: Any, original: str, user_text: str, presence: str, relationship: str, voice: str) -> str:
        """回复二次润色与人格校准：交由「润色」模块（可编辑模板 + 占位符 + 缓冲面板）。"""
        if not self._config().bool("rewrite.enabled", True):
            return original
        try:
            polisher = getattr(self._plugin, "polisher", None)
            if polisher is None or not callable(getattr(polisher, "polish", None)):
                return original
            polished = await polisher.polish(event, original)
            return polished or original
        except Exception as exc:
            logger.warning("[Storyteller] 二次润色失败: %s", exc)
            return original

    async def _judge(self, rewritten: str, user_text: str, presence: str, relationship: str) -> dict[str, Any] | None:
        if not self._config().bool("pipeline.judge_enabled", True):
            return {"action": "send", "text": rewritten}
        try:
            # 表情包语境判定用独立名额（emoji.judge_provider_id）；未配置时按「留空回退模型」策略解析
            provider, provider_id = resolve_chat_provider(self._plugin.context, self._config(), "emoji_judge")
            if provider is None:
                provider, provider_id = resolve_chat_provider(self._plugin.context, self._config(), "judge")
            if provider is None:
                return {"action": "send", "text": rewritten}
            if relationship:
                presence = (presence + "\n" + relationship).strip() if presence else relationship
            prompt = build_judge_prompt(rewritten, user_text, presence, self._categories())
            resp = await chat_text(provider, self._config(), prompt=prompt, session_id="storyteller_judge")
            self._record("judge", provider_id or "default", resp)
            result = parse_judge(str(getattr(resp, "completion_text", "") or ""))
            return result or {"action": "send", "text": rewritten}
        except Exception as exc:
            logger.warning("[Storyteller] 判定失败: %s", exc)
            return {"action": "send", "text": rewritten}

    def _profile_text(self, event: Any) -> str:
        """从【为你篆刻的历史】插件取当前用户轻量画像（称呼 + 最近偏好/关系）。"""
        try:
            bridge = self._plugin._get_memory_bridge()
            if bridge is None:
                return ""
            from .persona import extract_sender

            sender = extract_sender(event)
            user_id = sender.get("user_id") or ""
            session_id = sender.get("session_id") or ""
            platform = session_id.split(":", 1)[0] if ":" in session_id else ""
            parts: list[str] = []
            if user_id and platform:
                getter = getattr(bridge, "get_user", None)
                if callable(getter):
                    user = getter(f"{platform}:{user_id}")
                    if isinstance(user, dict):
                        name = str(user.get("name") or "").strip()
                        if name:
                            parts.append(f"对方称呼：{name}")
            lister = getattr(bridge, "list_recent_memories", None)
            if callable(lister) and user_id:
                records = lister(session_context={"user_id": user_id}, limit=4)
                if isinstance(records, list):
                    memories = []
                    for r in records[:4]:
                        if isinstance(r, dict):
                            content = str(r.get("content") or r.get("summary") or "").strip()
                            if content:
                                memories.append(content[:80])
                    if memories:
                        parts.append("关于对方：" + "；".join(memories))
            return "；".join(parts)
        except Exception:
            return ""
