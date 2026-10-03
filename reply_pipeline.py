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
# 0.195：用户明确索要表情包（「发个表情包」「来个表情」…）→ 直接发，不必等判定模型点头
EMOJI_ASK_PATTERN = re.compile(
    r"发[个张一]?表情|来个表情|来张表情|发表情包|发张表情|表情包发|发个表情包|整[个张]表情|给我发.*表情"
)

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


def build_judge_prompt(
    rewritten: str,
    user_text: str,
    presence: str,
    categories: list[str],
    *,
    extra: str = "",
    brief_enabled: bool = True,
    night_silence: bool = True,
) -> str:
    """智能沉默判定：沉默 / 草草回复 / 表情包 / 正常发送。

    extra：「当前情境」（此刻时间 + 她此刻在做什么），由 silence 模块组装——
    没有它，判定模型看不到日程，就永远判不出「这会儿她在睡，可以不回」。
    """
    from .silence import build_rules_text

    cat_hint = "、".join(f"「{c}」" for c in categories) if categories else "（尚未配置任何分类）"
    lines = [
        "下面是机器人准备好的一条回复。请判断它最终应该怎么发出去，只输出一个 JSON 对象，不要任何解释或代码块标记，字段固定为：",
        '{"action": "silence|brief|send", "text": "最终文本", "emoji": [{"category": "分类标题", "position": "start|end"}]}',
        "",
        build_rules_text(brief_enabled=brief_enabled, night_silence=night_silence),
        "- 只有当情绪/状态确实需要表情包时，才在 emoji 里填：category 必须是下面可用分类之一，position 为 start（表情包在文字前）或 end（表情包在文字后），并同时在 text 对应位置插入占位符 [EMOJI:分类标题]；",
        f"- 可用表情包分类：{cat_hint}；不要用不存在的分类，不要每句都带表情，不要插错语境。",
    ]
    if extra:
        lines.append(extra)
    if presence:
        lines.append(f"机器人此刻的状态：{presence}")
    lines.append(f"用户消息：{user_text[:600]}")
    lines.append(f"机器人准备回复：{rewritten[:1400]}")
    return "\n".join(lines)


def build_emoji_prompt(reply_text: str, user_text: str, categories: list[str]) -> str:
    """0.193：接管改换链路的「是否配表情包」轻量判定（只判表情包，不改文本）。"""
    cat_hint = "、".join(f"「{c}」" for c in categories) if categories else "（无可用分类）"
    return "\n".join([
        "判断下面这条准备好的回复，此刻是否适合再配一张表情包（多数时候不需要，只在情绪/语气确实到位时才配）。",
        "只输出一个 JSON 对象，不要解释、不要代码块：",
        '{"emoji": [{"category": "分类标题", "position": "start|end"}]}',
        '不适合就输出 {"emoji": []}。',
        f"- 可用分类（必须从中选，不要编造）：{cat_hint}",
        f"- 对方刚说：{user_text[:200]}",
        f"- 准备回复：{reply_text[:600]}",
    ])


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

    def _usable_categories(self) -> list[str]:
        """0.193：只返回「真的还有图片」的分类（空分类配不出来，别让模型白选）。"""
        store = getattr(self._plugin, "emoji_store", None)
        if store is None:
            return []
        out: list[str] = []
        for cat in self._categories():
            try:
                cid = store._title_to_id(cat)
                if cid and store._files(cid):
                    out.append(cat)
            except Exception:
                continue
        return out

    def _emoji_allowed(self, text: str, event: Any) -> bool:
        """发送闸门：用户 opt-out 直接拒；否则按 emoji.send_probability（含反馈权重）抽签。"""
        import random

        store = getattr(self._plugin, "emoji_store", None)
        user = ""
        try:
            from .persona import extract_sender

            user = extract_sender(event).get("user_id") or ""
        except Exception:
            user = ""
        if not user:
            # 兜底：直接从事件/消息对象取发送者 ID（部分平台事件无 get_sender_id）
            try:
                getter = getattr(event, "get_sender_id", None)
                if callable(getter):
                    user = str(getter() or "")
                if not user:
                    sender = getattr(getattr(event, "message_obj", None), "sender", None)
                    user = str(getattr(sender, "user_id", "") or "")
            except Exception:
                user = ""
        if store is not None:
            try:
                if store.is_opt_out(user):
                    return False
            except Exception:
                pass
        try:
            prob = max(0.0, min(1.0, float(self._config().float("emoji.send_probability", 0.25))))
        except Exception:
            prob = 0.25
        if store is not None and user:
            try:
                weights = []
                for m in EMOJI_PATTERN.finditer(text):
                    title = str(m.group(1) or "").strip()
                    cid = store._title_to_id(title)
                    if cid:
                        weights.append(store.weight_for(user, cid))
                if weights:
                    prob = max(0.0, min(1.0, prob * (sum(weights) / len(weights))))
            except Exception:
                pass
        return random.random() <= prob

    async def apply_emoji_pick(self, event: Any, text: str) -> str:
        """0.193：接管改换链路专用——判定「这轮要不要配表情包」，命中则插入 [EMOJI:分类] 占位符。

        主链路径由 process() 的判定模型一并完成；接管是插件直连生成、绕过判定，此前永远
        没有占位符可渲染（用户实测「表情包不会被发送」的根因）。这里补上这一步：
        有图的分类才参选 → 轻量判定 → 概率/opt-out/权重闸门 → 插入占位符（渲染仍走原链路）。
        """
        if not text or EMOJI_PATTERN.search(text):
            return text
        try:
            if not self._config().bool("emoji.enabled", True):
                return text
        except Exception:
            return text
        categories = self._usable_categories()
        if not categories:
            return text
        user_text = ""
        try:
            user_text = str(getattr(event, "message_str", "") or "").strip()
        except Exception:
            user_text = ""
        # 0.195：用户明确索要表情包 → 直接带一张（跳过判定与概率闸，这是明确指令不是语气判断）
        try:
            if user_text and EMOJI_ASK_PATTERN.search(user_text):
                title = categories[0]
                logger.info("[Storyteller] 用户明确索要表情包 → 直接发送: category=%s", title)
                return f"{text} [EMOJI:{title}]"
        except Exception:
            pass
        provider, provider_id = resolve_chat_provider(self._plugin.context, self._config(), "emoji_judge")
        if provider is None:
            provider, provider_id = resolve_chat_provider(self._plugin.context, self._config(), "judge")
        if provider is None:
            return text
        try:
            resp = await chat_text(
                provider, self._config(),
                prompt=build_emoji_prompt(text, user_text, categories),
                session_id="storyteller_emoji_pick",
            )
            self._record("emoji_judge", provider_id or "default", resp)
            data = parse_judge(str(getattr(resp, "completion_text", "") or ""))
            picks = (data or {}).get("emoji") if isinstance(data, dict) else None
            if not isinstance(picks, list) or not picks:
                return text
            first = picks[0] if isinstance(picks[0], dict) else {}
            title = str(first.get("category") or "").strip()
            position = str(first.get("position") or "end").strip().lower()
            if title not in categories:
                # 容错：模型写了个近似名字（含/被含）也认
                title = next((c for c in categories if c and (c in title or title in c)), "")
            if not title:
                return text
            placeholder = f"[EMOJI:{title}]"
            if not self._emoji_allowed(placeholder, event):
                logger.info("[Storyteller] 表情包判定命中但概率闸未过: %s", title)
                return text
            out = f"{placeholder} {text}" if position == "start" else f"{text} {placeholder}"
            logger.info("[Storyteller] 表情包已插入占位符: category=%s position=%s", title, position)
            return out
        except Exception as exc:
            logger.warning("[Storyteller] 表情包判定失败（跳过）: %s", exc)
            return text

    def _presence_text(self) -> str:
        try:
            from .presence import build_presence_anchor

            return build_presence_anchor(self._plugin.presence_store.load())
        except Exception:
            return ""

    async def judge_for_takeover(self, event: Any, reply_text: str) -> dict[str, Any] | None:
        """0.195：接管改换链路专用——判定「沉默 / 草草回复 / 正常发送」。

        主链路径由 process() 内建判定；接管是插件直连生成，此前完全绕过判定，
        导致「用户每条消息都必回」（不会主动沉默）。这里补上同一判定。
        """
        try:
            from . import silence as silence_mod

            if not silence_mod.enabled(self._config()):
                return None
            user_text = str(getattr(event, "message_str", "") or "").strip()
            return await self._judge(reply_text, user_text, self._presence_text(), self._relationship_text(event))
        except Exception as exc:
            logger.warning("[Storyteller] 接管回复判定异常: %s", exc)
            return None

    async def process(self, event: Any, resp: Any) -> str:
        """处理主链回复，返回最终 completion_text（可能含表情包占位符）。"""
        original = squeeze_reply(str(getattr(resp, "completion_text", "") or ""))
        if not original:
            return ""
        from . import silence as silence_mod
        user_text = str(getattr(event, "message_str", "") or "").strip()
        presence = self._presence_text()
        relationship = self._relationship_text(event)
        voice = _voice_desc(self._plugin.voice_store.load())

        rewritten = await self._rewrite(event, original, user_text, presence, relationship, voice)
        if not rewritten:
            return original
        judged = await self._judge(rewritten, user_text, presence, relationship)
        judged = silence_mod.apply_decision(self._plugin, event, judged, rewritten)
        action = judged["action"]
        if action == "silence":
            logger.info("[Storyteller] 判定沉默，不回复: session=%s", getattr(event, "unified_msg_origin", ""))
            return ""
        if action == "brief":
            from . import silence as silence_mod

            if not silence_mod.brief_enabled(self._config()):
                return rewritten            # 草草回复已关闭 → 按正常回复发
            text = str(judged.get("text") or "").strip()
            if len(text) > 20:              # 保险：brief 只该是极短反应
                return rewritten
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
        from . import silence as silence_mod

        config = self._config()
        if not silence_mod.enabled(config):
            return {"action": "send", "text": rewritten}
        try:
            # 0.234：沉默判定改用**自己的**模型名额（silence.provider_id），
            # 不再借用 emoji.judge_provider_id（那个名额另有表情包语境判定在用）；
            # 旧键 pipeline.provider_id / models.judge_provider_id 由 models 的兼容键继续读取。
            provider, provider_id = resolve_chat_provider(self._plugin.context, config, "judge")
            if provider is None:
                return {"action": "send", "text": rewritten}
            if relationship:
                presence = (presence + "\n" + relationship).strip() if presence else relationship
            prompt = build_judge_prompt(
                rewritten, user_text, presence, self._categories(),
                extra=silence_mod.build_context_block(self._plugin, config),
                brief_enabled=silence_mod.brief_enabled(config),
                night_silence=silence_mod.night_silence(config),
            )
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
                records = lister(session_context=self._plugin._session_ctx_dict(event), limit=4)
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
