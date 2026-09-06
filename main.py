"""为你续写的故事：AstrBot 陪伴插件。

承载插件生命周期、数据目录、外观、消息防抖、主链 LLM 请求拦截、
拟人化锚注入（身份/风格/状态/日程）、记忆写入与用户画像、智能主动对话。
"""

from __future__ import annotations

import asyncio
import importlib
import re
import time
from pathlib import Path
from typing import Any

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, StarTools

from . import PLUGIN_DISPLAY, PLUGIN_NAME, PLUGIN_VERSION
from .appearance import AppearanceManager
from .config import ConfigView
from .debounce import DebounceManager
from .diary import DiaryStore, build_diary_prompt
from .emoji import EmojiStore
from .image_gen import ImageGen, detect_image_intent
from .intercept import InterceptBuffer, SentRequestBuffer, utc_now
from .log import logger, setup as setup_logging
from .memory import (
    build_commitment_prompt,
    build_profile_prompt,
    build_session_context,
    detect_commitment,
    detect_profile,
    parse_profile_items,
    write_memory,
)
from .mind import MindStore
from .models import chat_text, resolve_chat_provider
from .page_api import StorytellerWebApi
from .persona import build_identity_anchor, extract_sender
from .persona_profile import PersonaStore
from .presence import PresenceStore, build_presence_anchor
from .proactive import ProactiveManager
from .relationship import RelationshipStore, build_relationship_anchor
from .reply_buffer import ReplyBufferManager
from .reply_pipeline import ReplyPipeline, squeeze_reply
from .reply_polish import ReplyPolisher
from .rewrite import assemble_request, rewrite_user_message
from .schedule import ScheduleStore, build_schedule_anchor, current_activity
from .token_usage import TokenStore
from .ui_state import UiStateStore
from .vision import (
    attach_file_link_notes,
    build_media_note,
    build_ordered_media_script,
    caption_and_inject,
    extract_media_parts,
)
from .voice import VoiceStore, build_voice_anchor
from .wardrobe import WardrobeStore, build_wardrobe_anchor


def _data_directory() -> Path:
    directory = Path(StarTools.get_data_dir(PLUGIN_NAME))
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _hhmm() -> str:
    return time.strftime("%H:%M", time.localtime())


def _labelize_anchors(template: str, anchors: dict) -> dict:
    """给模板里的裸占位符内容加语义标签（0.164/0.165）。

    用户模板替换后 {当前说话}/{当前用户}/{场合}/{上下文}/{记忆}/{天气}/{见闻} 是裸文本，
    模型分不清谁说了什么/内容属于哪一类（0.162 曾用"末尾补丁"补救→与裸文本并存重复混乱，0.164 改为源头加标签）。
    本函数：仅当模板中该占位符相邻文本没有标签词时，给内容加对应前缀。
    """
    try:
        t = str(template or "")
        out = dict(anchors)
        def ctx_of(ph: str) -> str:
            idx = t.find(ph)
            if idx < 0:
                return ""
            return t[max(0, idx - 14):idx]
        if not any(k in ctx_of("{当前说话}") for k in ("说", "话", "讲")):
            v = str(out.get("current_text") or "").strip()
            if v:
                out["current_text"] = "【对方刚刚说的话】\n" + v
        if not any(k in ctx_of("{当前用户}") for k in ("对话", "人", "用户", "聊")):
            v = str(out.get("current_user") or "").strip()
            if v:
                out["current_user"] = "【当前和你对话的人】\n" + v
        if not any(k in ctx_of("{场合}") for k in ("场合", "境")):
            v = str(out.get("place") or "").strip()
            if v:
                out["place"] = "【发送场合】\n" + v
        if not any(k in ctx_of("{上下文}") for k in ("对话", "记录", "上文", "历史")):
            v = str(out.get("context") or "").strip()
            if v:
                out["context"] = "【在此之前的部分上下文】\n" + v
        if not any(k in ctx_of("{记忆}") for k in ("记忆", "记得", "记住", "想起")):
            v = str(out.get("memory") or "").strip()
            if v:
                out["memory"] = "【你的部分记忆】\n" + v
        if not any(k in ctx_of("{天气}") for k in ("天气", "天")):
            v = str(out.get("weather") or "").strip()
            if v:
                out["weather"] = "【今天天气】\n" + v
        if not any(k in ctx_of("{见闻}") for k in ("见闻", "看到", "见")):
            v = str(out.get("mind") or "").strip()
            if v:
                out["mind"] = "【你刚看到的见闻】\n" + v
        return out
    except Exception:
        return anchors


def _clean_memory_meta(text: str) -> str:
    """清洗记忆注入包里的「元信息句」（如"XX在XX时间给我发了消息。这条消息旨在说明…"）。

    这类句子让模型以为"对方发过一条它没看到的消息"（实机 17:58"刚才走神了。再说一遍吧。"的触发点），
    剔除含"旨在/与亲密度无关"等标志的行。
    """
    t = str(text or "")
    if not t:
        return t
    try:
        lines = [ln.strip() for ln in t.split("\n") if ln.strip()]
        kept = [
            ln for ln in lines
            if not any(k in ln for k in ("旨在", "这条消息旨在", "与亲密度", "与互动等无关", "希望你了解"))
        ]
        return "\n".join(kept)
    except Exception:
        return t


def _looks_asking_context(text: str) -> bool:
    """检测回复是否在「索要设定/上下文」或「装没听见」（演没收到对方消息）。
    宽召回（宁可多拦——拦错只多一次重生成，正常句无感）：提及设定/上下文/代入类词 + 索要句式；
    或"道歉式"强信号（抱歉+没看到+设定/上下文）；或没听清/没注意/再说一遍类"装没听见"。
    """
    t = str(text or "")
    if not t:
        return False
    mention = any(k in t for k in (
        "设定", "上下文", "角色设定", "身份设定", "什么情境", "什么角色",
        "代入", "具体的前文", "前文对话", "没有看到", "没看到", "看不到", "没有告诉我", "不知道应该以",
    ))
    ask = any(k in t for k in (
        "请补充", "补充一下", "能补充", "告诉我", "发给我", "给我", "提供",
        "再接上", "我好接", "帮我把", "请提供", "可以再", "再描述", "描述一下",
        "这样我好", "才能更好地", "才能更好", "好代入", "让我代入", "让我更好",
        "麻烦你", "麻烦您", "请再", "请您再", "重新发", "发一下",
    ))
    if mention and ask:
        return True
    # 装没听见：模型"演没收到消息"（实机 17:58"啊？你刚刚说了什么？我没太注意，再说一遍呗？"）
    if any(k in t for k in (
        "再说一遍", "再说一次", "没听清", "没听到", "没注意", "走神了", "走神了？",
        "刚才说了什么", "刚刚说了什么", "你刚刚说什么", "再说一遍呗",
    )):
        return True
    # 道歉式强信号：抱歉/没看到 + 设定/上下文（模型"诚实"索要的口头禅组合）
    if ("设定" in t or "上下文" in t) and any(k in t for k in ("抱歉", "没有看到", "没看到", "看不到", "暂时不知道", "我这边没有")) and len(t) <= 100:
        return True
    return False


class StorytellerPlugin(Star):
    """陪伴插件主类：管理各功能模块、配置与面板后端接口。"""

    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.context = context
        self.data_dir = _data_directory()
        setup_logging(self.data_dir)
        self.raw_config = config if isinstance(config, dict) else {}
        self.config = ConfigView(self.raw_config)
        self.appearance = AppearanceManager(self.data_dir)
        self.intercept = InterceptBuffer(self.config.int("intercept.max_records", 50))
        self.sent = SentRequestBuffer(30)
        self.debounce = DebounceManager(self)
        self.voice_store = VoiceStore(self.data_dir)
        self.presence_store = PresenceStore(self.data_dir)
        self.schedule_store = ScheduleStore(self.data_dir)
        self.wardrobe_store = WardrobeStore(self.data_dir)
        self.proactive = ProactiveManager(self)
        from .inspiration import InspirationEngine

        self._inspiration_engine = InspirationEngine(self)
        self.relationship_store = RelationshipStore(self.data_dir)
        self.mind_store = MindStore(self.data_dir)
        self.diary_store = DiaryStore(self.data_dir)
        self.persona_store = PersonaStore(self.data_dir)
        self.token_store = TokenStore(self.data_dir)
        self.emoji_store = EmojiStore(self.data_dir)
        self.ui_state = UiStateStore(self.data_dir)
        self.image_gen = ImageGen(self, self.data_dir)
        self.reply_pipeline = ReplyPipeline(self)
        self.polisher = ReplyPolisher(self)
        self.reply_buffer = ReplyBufferManager(self)
        self.web = StorytellerWebApi(self)
        self.web.mount(context)
        self._memory_managed_checked = False
        self._memory_managed_active = False
        self._image_wish_cache: dict[str, tuple[str, float]] = {}  # 0.183：会话 -> ({生图意愿} 标记文本, 时间戳)
        try:
            self._migrate_intercept_template()
        except Exception:
            pass
        self._profile_buffer: list[dict[str, Any]] = []
        self._emotion_buffer: list[str] = []
        self._last_identity_anchor: str = ""
        self._interaction_buffer: dict[str, list[str]] = {}
        self._last_emotion_refresh: float = 0.0
        self._last_presence_beat: float = 0.0
        self._profile_task: asyncio.Task | None = None
        logger.info(
            "%s 已加载 v%s，数据目录=%s",
            PLUGIN_DISPLAY,
            PLUGIN_VERSION,
            self.data_dir,
        )

    def _migrate_intercept_template(self) -> None:
        """0.184：旧版默认拦截模板（11 个占位符）被保存进配置后，新默认模板不生效——
        若配置值仍等于旧默认串，自动升级为完整模板（17 个占位符全应用），写配置并刷新运行时。
        自定义过模板（不等于任何旧默认）则不动。
        """
        import json as _json

        try:
            from .intercept import DEFAULT_TEMPLATE, LEGACY_DEFAULT_TEMPLATE
        except Exception:
            return
        current = str(self.config.get("intercept.template", "") or "").strip()
        if not current or current != LEGACY_DEFAULT_TEMPLATE.strip():
            return
        cfg_path = Path(self.data_dir).parent.parent / "config" / "astrbot_plugin_storyteller_config.json"
        raw: dict = {}
        try:
            if cfg_path.exists():
                raw = _json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        except Exception:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        raw.setdefault("intercept", {})["template"] = DEFAULT_TEMPLATE
        try:
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(
                _json.dumps(raw, ensure_ascii=False, indent=2),
                encoding="utf-8-sig",
            )
        except Exception:
            pass
        self.raw_config = raw
        self.config = ConfigView(raw)
        logger.info("[Storyteller] 拦截模板已自动升级为新默认（全部占位符应用，共 17 个）")

    # ------------------------------------------------------------ 消息入口

    @filter.event_message_type(filter.EventMessageType.ALL, priority=60)
    async def on_message_debounce(self, event: AstrMessageEvent):
        """消息防抖：窗口内静默收集，到期合并后重构锚事件放行。"""
        await self.debounce.handle(event)

    @filter.event_message_type(filter.EventMessageType.ALL, priority=65)
    async def on_message_observe(self, event: AstrMessageEvent):
        """消息观察：记录互动与关系演进、收集画像素材、检测约定/愿望（不阻断消息）。"""
        try:
            if self._is_self_message(event):
                return  # 平台回显的自身消息：不当作对方的消息观察/记录
            self._last_talk_ts = time.time()
            self.proactive.note_interaction(event)
            # 发送缓冲：缓存未发完时用户抢话 → 抢话裁决（A 提速发完 / B 丢弃带上下文重组织）
            buffer = getattr(self, "reply_buffer", None)
            if buffer is not None:
                try:
                    buffer.on_user_message(event)
                except Exception:
                    pass
            self._touch_relationship(event)
            self._observe_message(event)
        except Exception as exc:
            logger.warning("[Storyteller] 消息观察异常: %s", exc)

    def _detect_emoji_preference(self, event: AstrMessageEvent, text: str) -> None:
        """表情包显式偏好 + 反馈学习：明说「别发表情包」→ opt-out；「可以发」→ opt-in。

        反馈学习（轻量）：上一条回复刚带过表情包（近 30 分钟内）且用户现在说正面/负面词
        （喜欢/哈哈 → 该类升权；烦/别发/无语 → 该类降权）。
        """
        if not text:
            return
        store = getattr(self, "emoji_store", None)
        if store is None:
            return
        try:
            from .persona import extract_sender

            user = extract_sender(event).get("user_id") or ""
        except Exception:
            return
        if not user:
            return
        compact = re.sub(r"\s+", "", text)
        opt_out_words = ("别发表情", "不要发表情", "不用表情", "别老发图", "别发图", "别发图片", "别用表情")
        opt_in_words = ("可以发表情", "可以发图", "可以发图片", "恢复表情", "能用表情", "可以发表情包")
        try:
            if any(w in compact for w in opt_out_words):
                if not store.is_opt_out(user):
                    store.set_opt_out(user, True)
                    logger.info("[Storyteller] 用户表达不想看表情包，已停用自动表情: user=%s", user)
            elif any(w in compact for w in opt_in_words):
                if store.is_opt_out(user):
                    store.set_opt_out(user, False)
                    logger.info("[Storyteller] 用户恢复表情包偏好: user=%s", user)
            # 反馈学习：最近聊得近用户反馈（正面/负面词）→ 分类权重
            recent = store.sent_log(limit=5)
            if recent:
                last = recent[0]
                try:
                    import time as _t

                    at = last.get("at") or ""
                    ts = _t.mktime(_t.strptime(at, "%Y-%m-%d %H:%M:%S"))
                    if _t.time() - ts < 1800:
                        cid = str(last.get("cid") or "")
                        negative = any(w in compact for w in ("别", "烦", "无语", "不喜欢", "不好笑", "删了"))
                        positive = any(w in compact for w in ("哈哈", "喜欢", "可爱", "好笑", "爱了", "太懂了", "笑死"))
                        if (negative or positive) and cid:
                            store.feedback(user, cid, negative=negative)
                            logger.info(
                                "[Storyteller] 表情包反馈: user=%s cid=%s negative=%s",
                                user, cid, negative,
                            )
                except Exception:
                    pass
        except Exception:
            pass

    def _observe_media(self, event: AstrMessageEvent, text: str) -> None:
        """媒体互动信号（轻量规则，不调 LLM）：纯表情包/图片/文件/链接也算互动。

        - 关系/画像：纯媒体消息记一条画像素材（对方喜欢分享图片/表情等交流方式）；
        - 互动缓冲：媒体附注进关系判断素材，让「最近印象」能感知到对方常发图。
        """
        try:
            parts = extract_media_parts(event)
            if not parts["has_media"]:
                return
            sender_id = extract_sender(event).get("user_id") or ""
            tags: list[str] = []
            if parts["images"]:
                tags.append(f"图片×{len(parts['images'])}")
            if parts["faces"]:
                tags.append(f"表情×{parts['faces']}")
            if parts["files"]:
                tags.append(f"文件×{len(parts['files'])}")
            if parts["urls"]:
                tags.append(f"链接×{len(parts['urls'])}")
            if parts["videos"]:
                tags.append(f"视频×{len(parts['videos'])}")
            if parts["records"]:
                tags.append(f"语音×{len(parts['records'])}")
            note = "、".join(tags)
            if sender_id:
                buf = self._interaction_buffer.setdefault(sender_id, [])
                buf.append(f"[媒体] {note}"[:100])
                if len(buf) > 100:
                    del buf[: len(buf) - 100]
            if not text:
                # 纯媒体消息：也是一次交流（画像素材，供提炼「对方用什么方式交流」）
                self._profile_buffer.append(
                    {"text": f"对方发来{note}", "ctx": build_session_context(event)}
                )
                if len(self._profile_buffer) > 200:
                    self._profile_buffer = self._profile_buffer[-200:]
                if len(self._profile_buffer) >= 20:
                    asyncio.ensure_future(self._flush_profile())
        except Exception:
            pass

    def _touch_relationship(self, event: AstrMessageEvent) -> None:
        """记录互动并演进关系（互动基础 + 情感质量）。"""
        try:
            sender = extract_sender(event)
            user_id = sender.get("user_id") or ""
            if not user_id:
                return
            text = str(getattr(event, "message_str", "") or "")
            if not text:
                # 纯媒体消息（图片/表情/文件/链接）也算轻度互动
                try:
                    media = extract_media_parts(event)
                    delta = 0.012 if media["has_media"] else 0.005
                except Exception:
                    delta = 0.005
            else:
                delta = self._affection_delta(text)
            self.relationship_store.touch(
                user_id,
                delta=delta,
                address=sender.get("user_name") or "",
            )
        except Exception:
            pass

    @staticmethod
    def _affection_delta(text: str) -> float:
        """轻量检测本轮互动的情感质量（正向拉近 / 负向疏远 / 中性微增）。"""
        t = (text or "").strip()
        if not t:
            return 0.005
        positive = ("喜欢", "爱你", "谢谢", "开心", "想你", "真棒", "厉害", "好贴心", "抱抱", "爱你哦", "爱了", "温柔", "靠谱")
        negative = ("讨厌", "别烦", "走开", "滚", "烦死", "不想理", "别说了", "闭嘴", "无语了", "呵呵")
        if any(w in t for w in positive):
            return 0.05
        if any(w in t for w in negative):
            return -0.05
        return 0.005

    async def _judge_relationship(self, user_id: str, texts: list[str]) -> None:
        """批量互动后由 LLM 精确判断关系变化并提炼「最近印象」。

        - 调用 judge/关系判断模型（pipeline.provider_id，关系页内可配）；
        - 输出同时含情感 delta（写好感度）与「最近印象」（写人物卡 impression）；
        - 节流：距上次印象提炼不足 impression_min_interval 分钟则本次跳过（防高频烧 token）；
        - 触发条数由 relationship.impression_batch 控制（在消息观察层判断）。
        """
        try:
            from .models import resolve_chat_provider
            from .relationship import stage_for

            current = self.relationship_store.get(user_id)
            # 节流：距上次提炼不足最短间隔则不触发（也暂不微调）
            min_interval = max(1, self.config.int("relationship.impression_min_interval", 30)) * 60
            last = str(current.get("impression_updated_at", "") or "")
            if last:
                try:
                    from datetime import datetime as _dt

                    last_ts = _dt.strptime(last, "%Y-%m-%d %H:%M:%S").timestamp()
                except Exception:
                    last_ts = 0.0
                if time.time() - last_ts < min_interval:
                    return
            provider, provider_id = resolve_chat_provider(self.context, self.config, "judge")
            if provider is None:
                return
            stage = stage_for(float(current.get("affection", 0.15)))
            joined = "\n".join(f"- {t}" for t in texts[:15])
            prompt = (
                "下面是 Bot 和一位用户最近的一些互动（用户说的话）。请同时完成两件事：\n"
                "1) 判断这些互动对关系的整体影响（情感质量）；\n"
                "2) 用一句话提炼你目前对这位用户的「最近印象」（像人记得对方是怎样的存在，例如'最近挺累但愿意跟我吐露心事'，克制、不夸张）。\n"
                "只输出一个 JSON 对象，不要任何解释或代码块标记："
                '{"delta": 数值, "impression": "最近印象", "reason": "简短原因"}\n'
                "delta 范围 -0.1 到 0.1：正值表示关系在拉近（对方信任、亲近、开心、依赖），"
                "负值表示在疏远（对方冷淡、不耐烦、敷衍、冲突），0 表示中性。\n"
                "要克制：除非有明显信号，否则 delta 接近 0；一次两次热情不等于关系质变；"
                "没有明显印象就 impression 给空字符串。\n\n"
                f"当前关系阶段：{stage}\n\n最近互动：\n{joined}"
            )
            resp = await chat_text(provider, self.config, prompt=prompt, session_id="storyteller_relationship_judge")
            self._record_usage(resp, "relationship", provider_id or "default")
            from .json_util import parse_json_lenient
            import re as _re

            text_out = str(getattr(resp, "completion_text", "") or "")
            delta = 0.0
            reason = ""
            impression = ""
            try:
                value = parse_json_lenient(text_out)
                if isinstance(value, dict):
                    delta = float(value.get("delta", 0.0) or 0.0)
                    reason = str(value.get("reason", "") or "")[:80]
                    impression = str(value.get("impression", "") or "").strip()[:120]
            except Exception:
                match = _re.search(r"-?0?\.\d+", text_out)
                if match:
                    delta = float(match.group(0))
            delta = max(-0.1, min(0.1, delta))
            if delta:
                self.relationship_store.touch(user_id, delta=delta * 0.5)
            if impression:
                self.relationship_store.set_impression(user_id, impression)
            logger.info(
                "[Storyteller] 关系判断: user=%s delta=%.3f impression=%s reason=%s -> %.3f",
                user_id, delta, impression or "-", reason or "-",
                float(self.relationship_store.get(user_id).get("affection", 0)),
            )
        except Exception as exc:
            logger.warning("[Storyteller] 关系判断失败: %s", exc)

    # ------------------------------------------------------------ 主链 LLM 请求拦截/托管

    @filter.on_llm_request(priority=10000)
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """主链 LLM 请求前的介入（priority=10000 先于【为你篆刻的历史】插件的注入 -20 执行）。

        介入方式（拦截参与总开关开启时，按 intercept.mode）：
        - 监视：什么都不管只记录，主链原样发送；
        - 放行：注入身份/关系/风格/状态/日程锚 + 托管记忆注入，可选润色、识图，交主链回复；
        - 阻断：记录并 stop_event 静默（不发送 LLM，插件也不回复）；
        - 接管改换：按「拦＆改」模板组装提示词（模块占位符替换），直连接管模型生成回复并发送，
          随后 stop_event 阻断主链（防止双重回复）；接管模型被驳回/生成失败时静默阻断。
        命令消息（/ 前缀）不介入。
        """
        try:
            if self._is_self_message(event):
                # 平台回显的自身消息：静默阻断，防止机器人回复自己
                self._stop_llm(event)
                return
            text = str(getattr(event, "message_str", "") or "")
            message_obj = getattr(event, "message_obj", None)
            raw_text = self.debounce._raw_text(event, message_obj)
            if self.debounce._looks_command(text) or self.debounce._looks_command(raw_text):
                # 命令消息不介入；本插件不注入 → 恢复记忆插件自动注入
                self._sync_memory_managed(False)
                return
            # 生图意图（0.148）：明确请求画图 → 直连生图并发送，不进入干预流程（独立于拦截总开关）
            if self.config.bool("image.enabled", True):
                try:
                    if await self._maybe_handle_image_intent(event, text):
                        return
                except Exception as exc:
                    logger.warning("[Storyteller] 生图意图处理异常: %s", exc)
            if not self.config.bool("intercept.enabled", True):
                # 拦截参与总开关关闭：本插件完全不参与 → 记忆交给记忆插件自己注入
                self._sync_memory_managed(False)
                return
            from .intercept import MODE_BLOCK, MODE_MONITOR, MODE_TAKEOVER, MODE_TAKEOVER_MAINCHAIN, resolve_mode
            from .models import resolve_chat_provider as _resolve_intercept

            mode = resolve_mode(self.config.get("intercept.mode", "接管走主链"))
            prompt = str(getattr(req, "prompt", "") or "")
            system_prompt = str(getattr(req, "system_prompt", "") or "")
            session_id = str(getattr(event, "unified_msg_origin", "") or "")
            user_name = self._safe_call(event, "get_sender_name")
            blocked = mode == MODE_BLOCK or mode == MODE_TAKEOVER
            self.intercept.record_llm_request(
                {
                    "time": utc_now(),
                    "session_id": session_id,
                    "user_name": user_name,
                    "prompt": prompt[:2000],
                    "system_prompt": system_prompt[:2000],
                    "contexts": "（主链请求，on_llm_request）",
                    "image_urls": [],
                    "audio_urls": [],
                    "image_count": 0,
                    "blocked": blocked,
                    "mode": mode,
                }
            )
            self.intercept.record_user_request(
                {
                    "time": utc_now(),
                    "session_id": session_id,
                    "user_name": user_name,
                    "text": text[:2000],
                }
            )
            if mode == MODE_MONITOR:
                self._sync_memory_managed(False)  # 监视原样发送：记忆交给记忆插件自己注入
                self._record_sent(
                    mode=mode, event=event, system_prompt=system_prompt, prompt=prompt,
                    note="监视（未注入，原样发送）",
                )
                self._note_main_chain_input(event, req)
                return
            if mode == MODE_BLOCK:
                self._sync_memory_managed(False)  # 阻断不发送：恢复记忆插件自动注入常态
                self._stop_llm(event)
                self._record_sent(
                    mode=mode, event=event, system_prompt=system_prompt, prompt=prompt,
                    blocked=True, note="被阻断（静默，未发送 LLM）",
                )
                logger.info("[Storyteller] 拦截阻断: session=%s prompt=%s", session_id, prompt[:60])
                return
            if mode == MODE_TAKEOVER:
                self._sync_memory_managed(False)  # 直连回复记忆由 compose_injection 注入模板；主链被阻断
                await self._takeover_reply(event, req, text, prompt, system_prompt)
                return
            if mode == MODE_TAKEOVER_MAINCHAIN:
                self._sync_memory_managed(True)  # 改写主链请求并放行：模板含 compose 记忆，避免记忆插件双份注入
                await self._takeover_via_mainchain(event, req, text, prompt, system_prompt)
                return
            # ---- 放行模式：组装拟人化锚 + 润色/识图 + 托管记忆，交主链回复 ----
            anchors = self._anchor_values(event)
            assemble_request(
                req,
                identity=anchors.get("identity", ""),
                voice=anchors.get("voice", ""),
                presence=anchors.get("presence", ""),
                schedule=anchors.get("schedule", ""),
                relationship=anchors.get("relationship", ""),
            )
            # 可选：润色用户消息（走「润色模型」配置，驳回时跳过）
            if self.config.bool("rewrite.enabled", False) and text:
                provider, _pid = _resolve_intercept(self.context, self.config, "rewrite")
                if provider is not None:
                    voice = self.voice_store.load()
                    voice_desc = str(voice.get("tone") or "")
                    new_text = await rewrite_user_message(provider, text, voice_desc)
                    if new_text and new_text != text:
                        req.prompt = str(prompt).replace(text, new_text, 1)
                        logger.info("[Storyteller] 已润色用户消息: session=%s", session_id)
            # 图片识图：直连识图模型，把转述注入到图片位置的消息
            if self.config.bool("vision.enabled", True):
                await caption_and_inject(self, event, req)
                # 文件/链接会意：文本类文档摘要、链接标题与要点（受同一总开关与 vision.file_summary/link_summary 约束）
                if self.config.bool("vision.file_summary", True) or self.config.bool("vision.link_summary", True):
                    try:
                        await attach_file_link_notes(self, event, req)
                    except Exception as exc:
                        logger.warning("[Storyteller] 文件/链接会意注入失败: %s", exc)
            # 托管记忆注入
            if self.config.bool("memory.managed_injection", True):
                self._sync_memory_managed(True)  # 本插件将注入 → 托管记忆插件，避免双份
                bridge = self._get_memory_bridge()
                if bridge is not None:
                    injected = await self._inject_memory(bridge, event, req)
                    if injected:
                        logger.info("[Storyteller] 已托管注入记忆: session=%s", session_id)
            else:
                # 用户关闭托管：本插件不注入 → 恢复记忆插件自动注入（避免记忆消失）
                self._sync_memory_managed(False)
            # 记录最终发送给对话 LLM 的快照（放行注入后）
            self._record_sent(
                mode=mode, event=event,
                system_prompt=str(getattr(req, "system_prompt", "") or ""),
                prompt=str(getattr(req, "prompt", "") or ""),
                note="放行（注入锚与记忆后交主链）",
            )
            self._note_main_chain_input(event, req)
        except Exception as exc:
            logger.warning("[Storyteller] 主链拦截异常: %s", exc)
            try:
                if str(locals().get("mode", "")) in ("接管改换", "阻断"):
                    self._stop_llm(event)
            except Exception:
                pass

    # ------------------------------------------------------------ 拦＆改：接管改换支持

    def _timeout_reply_text(self) -> str:
        """「调用超时后的回复」文案（general.timeout_reply；空 = 静默）。"""
        try:
            return str(self.config.get("general.timeout_reply", "") or "").strip()
        except Exception:
            return ""

    async def _send_timeout_reply(self, event: Any) -> None:
        """超时/失败时直发一条「报错」说明。

        走 event.send 平台直发：不进 AstrBot 会话历史、不触发记忆插件捕获
        （无 on_llm_response、无事件重入）——它是 Bot 的报错，不是对话。
        文案为空或发送失败时静默。
        """
        text = self._timeout_reply_text()
        if not text:
            return
        try:
            from astrbot.api.event import MessageChain

            chain = MessageChain()
            chain.message(str(text)[:200])
            sender = getattr(event, "send", None)
            if callable(sender):
                await sender(chain)
                logger.info("[Storyteller] 已发送调用超时回复: %s", str(text)[:40])
            else:
                # 无 send 接口（非常规事件）：尝试 set_result 直达（仅部分版本记录历史）
                setter = getattr(event, "set_result", None)
                if callable(setter):
                    from astrbot.api.event import MessageEventResult

                    try:
                        setter(MessageEventResult().message(chain))
                    except Exception:
                        pass
        except Exception as exc:
            logger.warning("[Storyteller] 发送调用超时回复失败: %s", exc)

    async def _takeover_fallback(self, event: AstrMessageEvent, *, system_prompt: str, prompt: str, reason: str) -> None:
        """接管改换失败时的降级策略（intercept.takeover_fallback，0.147 起）。

        - 放行主链（默认）：不阻断，主链原样回复——Bot 永远不会「没反应」；
        - 提示文案：直发「调用超时后的回复」文案（为空则静默）后阻断；
        - 静默：原行为（阻断且无任何回复）。
        """
        mode = str(self.config.get("intercept.takeover_fallback", "放行主链") or "放行主链").strip()
        try:
            if mode == "提示文案":
                self._stop_llm(event)
                try:
                    await self._send_timeout_reply(event)
                except Exception:
                    pass
                self._record_sent(
                    mode="接管改换", event=event, system_prompt=system_prompt, prompt=prompt,
                    blocked=True, note=f"接管失败（{reason}），已按策略提示文案并阻断",
                )
                logger.warning("[Storyteller] 接管失败（提示文案策略）: %s", reason)
                return
            if mode == "静默":
                self._stop_llm(event)
                self._record_sent(
                    mode="接管改换", event=event, system_prompt=system_prompt, prompt=prompt,
                    blocked=True, note=f"接管失败（{reason}），已静默阻断",
                )
                logger.warning("[Storyteller] 接管失败（静默策略）: %s", reason)
                return
            # 默认「放行主链」：不阻断、不直发，交主链原样回复（至少 Bot 有回应）
            self._record_sent(
                mode="接管改换", event=event, system_prompt=system_prompt, prompt=prompt,
                blocked=True, note=f"接管失败（{reason}），已降级放行主链",
            )
            logger.warning("[Storyteller] 接管失败，已降级放行主链: %s", reason)
        except Exception as exc:
            logger.warning("[Storyteller] 接管降级处理异常: %s", exc)
            try:
                self._stop_llm(event)
            except Exception:
                pass

    async def _maybe_handle_image_intent(self, event: AstrMessageEvent, text: str) -> bool:
        """生图意图处理（0.148）：命中 → 直连生图 → 发送图片+说明 → 记录 → 阻断主链。

        - 未命中意图 / 未开启 / 每日上限到 / API 未配置 → 返回 False（不拦截，聊天照常）；
        - 生成成功：发送（图片 + 一句说明），回填记忆时间线 + 会话历史 + 日志，
          阻断主链防止双回复；
        - 生成失败：不阻断（放行聊天，避免用户被晾着），失败已记记录与日志。
        """
        # 0.178 分层：A0 规则直判 → A1 索图式短问+会话上文 → B 智能判定（实验）
        desc, via = await self._resolve_image_intent(event, text)
        if not desc:
            return False
        ok, why = await self.image_gen.can_generate()
        if not ok:
            return False  # 上限/未配置：不拦截，聊天照常（不做强拦，避免误触吞掉对话）
        session_id = str(getattr(event, "unified_msg_origin", "") or "")
        logger.info("[Storyteller] 生图意图命中: session=%s via=%s desc=%s", session_id, via, desc[:80])
        # 0.176：生成提示词注入 人格/世界观 + 气质 + 状态/穿搭 + 天气 + 当前活动，
        # 让画面贴合人物设定与环境（此前原样交给生图模型，形象常与设定不符）。
        prompt = self._compose_image_prompt(desc)
        path, note = await self.image_gen.generate(prompt, kind="text2img")
        if not path:
            logger.warning("[Storyteller] 生图失败（放行聊天）: %s", note)
            return False
        caption = str(self.config.get("image.caption", "给你画好啦～") or "给你画好啦～").strip()
        caption = caption if caption else ""  # 0.182：image.caption 可配；留空=图片单独发送不附文字
        try:
            from astrbot.api.event import MessageChain

            chain = MessageChain()
            chain.file_image(path)
            chain.message(caption)
            sender = getattr(self.context, "send_message", None)
            if callable(sender) and session_id:
                await sender(session_id, chain)
                logger.info("[Storyteller] 生图已发送: session=%s path=%s", session_id, path[-80:])
            else:
                return False
        except Exception as exc:
            logger.warning("[Storyteller] 生图发送失败: %s", exc)
            return False
        # 记录（防上下文/记忆断裂）：记忆时间线 + 会话历史
        try:
            self._note_bot_reply(event, f"[图片] {caption}（用户请求：{desc[:80]}）")
        except Exception:
            pass
        try:
            await self._archive_bot_reply_to_history(session_id, text, f"[图片] {caption}")
        except Exception:
            pass
        try:
            self._stop_llm(event)
        except Exception:
            pass
        return True

    # ------------------------------------------------------------ 生图意图分层（0.178）
    # 索图式短问（硬信号）：明确索图才硬生图（0.183：疑问式词降级为「生图意愿」软信号）
    _IMAGE_ASK_RE = re.compile(r"给我看看|给我看|让我看看|让我看|拍我看看|发我看看|我看看|给看看|看看呗|瞅瞅|瞅一下|看一下")
    # 疑问式弱信号：可能想看画面，但只是询问——打「{生图意愿}」标签交给对话 LLM，不硬生图
    _IMAGE_WEAK_ASK_RE = re.compile(r"啥样|什么样|什么样子|咋样|怎么样|好看吗|好看不|漂亮吗|美不美|瞧瞧")
    # 画面对象/景象词：上文含这些词才允许「上文主题命中」（防闲聊误吸）
    _IMAGE_SUBJECT_RE = re.compile(r"云|天空|天气|晚霞|夕阳|落日|日落|月亮|月光|星星|星空|雪|雨|花|海|湖|山|树|街|城市|风景|照片|图|猫|狗|鸟|宠物|彩虹|朝霞|晨光|夜景")
    # 泛词描述：这类描述需要结合上文主题（「照片/图」单独画会变成人像图）
    _IMAGE_GENERIC_DESC = ("照片", "拍", "图", "一张", "自拍")
    # 非画面任务词：即使含「看看」也是聊天（看安排/看消息等），不进入生图判定
    _IMAGE_NON_PICTURE = ("日程", "安排", "计划", "设置", "配置", "命令", "资料", "消息", "记录", "文件", "账单", "数据", "课", "作业", "工作", "通知", "说明", "文档")
    # 弱信号：只有命中才进入仲裁（避免每句聊天都调 LLM）
    _IMAGE_WEAK_SIGNAL = re.compile(r"看看|看下|发我|给我看|让我看|拍我|画|照|图|照片|头像|壁纸|自拍|生成")

    @staticmethod
    def _extract_image_subject(text: str) -> str:
        """从上文提取画面对象/景象词（云/天空/晚霞…），用于把泛化请求锚定到话题。"""
        m = StorytellerPlugin._IMAGE_SUBJECT_RE.search(str(text or ""))
        return m.group(0) if m else ""

    @staticmethod
    def _looks_image_ask(text: str) -> bool:
        t = str(text or "").strip()
        if not t or len(t) > 20:
            return False
        if any(w in t for w in StorytellerPlugin._IMAGE_NON_PICTURE):
            return False
        return bool(StorytellerPlugin._IMAGE_ASK_RE.search(t))

    async def _resolve_image_intent(self, event: Any, text: str) -> tuple[str, str]:
        """生图意图三分层（0.178；0.182 上下文主题锚定）。

        A0：规则直判（「拍一张自拍」「画只猫」等）——描述为泛词（照片/图/自拍）时
            结合同会话上文主题（云/天空/风景…），避免画出无关的人像图；
        A1：索图式短问（「给我看看？」「好看吗？」）+ 上文含画面对象词才命中——
            描述 = 上文的景象主题（如「你那边的云怎么样」→「云」）；
        B（实验开关）：上述未命中且含弱信号时调轻量 LLM 仲裁；未配置/超时=不拦截。
        """
        desc = detect_image_intent(text)
        if desc:
            # 泛词描述 → 用上文主题锚定（0.182：「拍个照发我」在聊云时应画云，不画人像）
            if any(g in desc for g in self._IMAGE_GENERIC_DESC):
                try:
                    session_id = str(getattr(event, "unified_msg_origin", "") or "")
                    prev = await self._image_recent_user_text(session_id, limit=2, window_seconds=900, exclude_text=text)
                    if prev:
                        subj = self._extract_image_subject(prev)
                        if subj:
                            return f"{subj}的景象", "rule"
                except Exception:
                    pass
            return desc, "rule"
        if self._looks_image_ask(text):
            try:
                session_id = str(getattr(event, "unified_msg_origin", "") or "")
                prev = await self._image_recent_user_text(session_id, limit=2, window_seconds=600, exclude_text=text)
                if prev:
                    subj = self._extract_image_subject(prev)
                    if subj:
                        # 0.182：只有上文真的在聊画面景象才命中（防「你皮肤怎么样→好看吗」误吸）
                        return f"{subj}的景象", "context"
            except Exception:
                pass
        # 0.183：疑问式弱信号（好看吗/啥样…）→ 不硬生图，打「{生图意愿}」软标记给对话 LLM 自决
        try:
            if self._image_wish_hint(event, text):
                return "", ""
        except Exception:
            pass
        if not self.config.bool("image.judge_enabled", False):
            return "", ""
        if not self._IMAGE_WEAK_SIGNAL.search(text):
            return "", ""
        if any(w in text for w in self._IMAGE_NON_PICTURE):
            return "", ""
        try:
            return await self._judge_image_intent(event, text)
        except Exception as exc:
            logger.warning("[Storyteller] 生图智能判定异常: %s", str(exc)[:120])
            return "", ""

    async def _image_recent_user_text(self, session_id: str, *, limit: int = 2, window_seconds: int = 600, exclude_text: str = "") -> str:
        """取同会话最近一条有效用户发言（非系统/操作/命令，时间窗内），用于 A1/锚定上文。

        0.185：deepmemory 的 capture(priority 1500) 先于 on_llm_request(10000) 执行，
        当前消息已写入时间线——必须排除「当前消息自己」（否则取到的是自己，
        「好看吗？」没有画面主题词 → A1/软信号/泛词锚定全部失效——实测现象）。
        """
        bridge = self._get_memory_bridge()
        if bridge is None:
            return ""
        getter = getattr(bridge, "get_timeline", None)
        if not callable(getter):
            return ""
        exclude = str(exclude_text or "").strip()
        events = getter(session_context={"session_id": session_id}, limit=int(limit) + 6) or []
        now = time.time()
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if str(ev.get("role") or "") != "user":
                continue
            if ev.get("is_system") or str(ev.get("kind") or "") == "op":
                continue
            at = str(ev.get("occurred_at") or "")
            if at:
                try:
                    ts = time.mktime(time.strptime(at[:19], "%Y-%m-%d %H:%M:%S"))
                    if now - ts > window_seconds:
                        continue
                except Exception:
                    pass
            content = str(ev.get("content") or "").strip()
            if not content:
                continue
            # 0.185 自引用排除：同内容/互为长串的跳过（当前消息已被 capture 写入）
            if exclude and (content == exclude or content in exclude or exclude in content):
                continue
            # 0.181：_looks_command 是 DebounceManager 实例方法（此前误 import 模块级 → ImportError
            # 被上层 try 吞掉，导致 A1 上文命中永远不触发——「给我看看？」走了普通对话）
            try:
                looks_cmd = getattr(self.debounce, "_looks_command", None)
                is_cmd = bool(callable(looks_cmd) and looks_cmd(content))
            except Exception:
                is_cmd = False
            if is_cmd:
                continue
            return content
        return ""

    async def _image_wish_hint(self, event: Any, text: str) -> bool:
        """0.183：疑问式弱信号（好看吗/啥样…）且上文在聊画面 → 打「{生图意愿}」软标记。

        只做标记（返回 True=已打标），不触发生图；标记文本由 _anchor_values 读取并替换进
        {生图意愿} 占位符（10 分钟生效）——生图侧产出、模板链替换，模块间只通过占位符联动。
        """
        weak = bool(self._IMAGE_WEAK_ASK_RE.search(str(text or "")))
        logger.info("[Storyteller] 生图意愿检测入口: text=%r weak=%s", str(text or "")[:30], weak)  # 0.186 诊断
        if not weak:
            return False
        session_id = str(getattr(event, "unified_msg_origin", "") or "")
        if not session_id:
            return False
        prev = await self._image_recent_user_text(session_id, limit=2, window_seconds=600, exclude_text=text)
        subj = self._extract_image_subject(prev or "")
        logger.info(
            "[Storyteller] 生图意愿检测: session=%s prev=%s subj=%s",
            session_id, (prev or "")[:40].replace("\n", " ") or "-", subj or "-",
        )
        if not prev or not subj:
            return False
        hint = (
            "【画面话题】对方可能想看一眼画面（上文在聊「" + subj + "」）——"
            "如果你觉得对方想看，可以自然地问一句要不要拍给他看（如「要我拍给你看吗？」）；"
            "但「好看吗/啥样」只是询问，别当成必须执行的要求，也不要解释成一堆话。"
        )
        self._image_wish_cache[session_id] = (hint, time.time())
        logger.info("[Storyteller] 生图意愿软标记: session=%s subj=%s", session_id, subj)
        return True

    async def _judge_image_intent(self, event: Any, text: str) -> tuple[str, str]:
        """B 层：轻量 LLM 仲裁（image.judge_provider_id / judge_timeout / judge_context_count）。

        输入 = 当前消息 + 同会话最近 N 条对话（含机器人回复，条数可配 1~8）
        + 语境（场合/时间）+ 输出约束 JSON；超时/未配置/解析失败 → 安全不拦截。
        """
        import asyncio as _asyncio

        from .json_util import parse_json_lenient
        from .models import resolve_chat_provider

        provider, provider_id = resolve_chat_provider(self.context, self.config, "image_judge")
        if provider is None:
            return "", ""
        session_id = str(getattr(event, "unified_msg_origin", "") or "")
        count = max(1, min(8, self.config.int("image.judge_context_count", 3) or 3))
        timeout = max(3, min(60, self.config.int("image.judge_timeout", 8) or 8))
        lines: list[str] = []
        bridge = self._get_memory_bridge()
        if bridge is not None:
            getter = getattr(bridge, "get_timeline", None)
            if callable(getter):
                try:
                    events = getter(session_context={"session_id": session_id}, limit=count) or []
                    for ev in reversed(events if isinstance(events, list) else []):
                        if not isinstance(ev, dict):
                            continue
                        if ev.get("is_system") or str(ev.get("kind") or "") == "op":
                            continue
                        who = "用户" if str(ev.get("role") or "user") == "user" else "你"
                        content = str(ev.get("content") or "").strip()[:120]
                        if content:
                            lines.append(f"- {who}：{content}")
                except Exception:
                    pass
        prompt = (
            "【任务】判断「当前消息」是否让机器人生成/绘制一张图片（而不是聊天、或查看已存在的照片）。\n\n"
            f"【当前消息】\"{str(text or '')[:120]}\"\n"
            "【最近对话·按时间正序】\n" + ("\n".join(lines) if lines else "- （无）") + "\n\n"
            "【判断规则】\n"
            "- 当前消息是「给我看看/拍我看看/让我看看」这类省略式请求，且上文在谈论某个画面景象"
            "（云、风景、照片、天气……）→ 判 TRUE，画面内容按上文主题描述；\n"
            "- 上文只是闲聊、没有画面对象 → 判 FALSE；\n"
            "- 机器人没有真实拍过照、也没有存图——用户「想看画面」就是让机器人画/生成；\n"
            "- 不要因为当前消息里有「看看」两个字就一律判 FALSE。\n\n"
            "【输出】只输出 JSON（不要任何解释或标记）：\n"
            '{"want_image": true/false, "reason": "一句话中文", "prompt": "want_image=true 时给 80 字内的画面描述"}'
        )
        try:
            resp = await _asyncio.wait_for(
                chat_text(provider, self.config, prompt=prompt, session_id="storyteller_image_judge", _max_tokens=300),
                timeout=timeout,
            )
        except Exception as exc:
            logger.warning("[Storyteller] 生图智能判定超时/失败: %s", str(exc)[:120])
            return "", ""
        self._record_usage(resp, "image_judge", provider_id or "default")
        text_out = str(getattr(resp, "completion_text", "") or "").strip()
        data = None
        try:
            data = parse_json_lenient(text_out)
        except Exception:
            data = None
        if isinstance(data, dict) and str(data.get("want_image") or "").lower() in ("true", "1", "yes"):
            desc = str(data.get("prompt") or "").strip()
            if desc:
                return desc[:200], "judge"
        reason = str(data.get("reason") if isinstance(data, dict) else "")[:60]
        logger.info("[Storyteller] 生图智能判定：不想要图（reason=%s）", reason or "-")
        return "", ""

    def _compose_image_prompt(self, desc: str) -> str:
        """0.176+0.186+0.187：组装生图提示词。

        0.187 收干净：**只发「画面内容」**——人物主题另加角色设定/气质/穿搭参考；
        **不再注入天气/心情/此刻在做**（实测「云的景象」注入"此刻在做：实验室"后，
        模型按生活状态画出了实验室窗边人物+云——生活状态不是画面需求）。
        """
        is_human = any(w in str(desc or "") for w in ("我", "你", "自拍", "人像", "人物", "正脸", "全身", "人"))
        parts = [f"画面内容：{desc}"]
        ctx: list[str] = []
        if is_human:
            try:
                persona = str(self.persona_store.injection_text() or "").strip()
                if persona:
                    ctx.append("角色设定（仅作为画面里人物的外观参考，背景与主题服从「画面内容」）：" + persona[:500])
            except Exception:
                pass
            try:
                tone = str(self.voice_store.load().get("tone") or "").strip()
                if tone:
                    ctx.append("角色气质（参考）：" + tone[:100])
            except Exception:
                pass
            try:
                outfit = self.wardrobe_store.current_outfit()
                items = [str(x).strip() for x in (outfit.get("items") or []) if str(x).strip()]
                if items:
                    ctx.append("角色穿搭（参考）：" + "、".join(items[:4]))
            except Exception:
                pass
        if ctx:
            parts.append("以下为人物外观参考（服从「画面内容」，不要改变画面主题）：")
            parts.extend(ctx)
        return "\n".join(parts)

    def _stop_llm(self, event: AstrMessageEvent) -> None:
        """阻断主链 LLM 调用（防抖/接管/阻断共用）。"""
        stop = getattr(event, "stop_event", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                pass

    def _record_sent(
        self,
        *,
        mode: str,
        event: AstrMessageEvent,
        system_prompt: str,
        prompt: str,
        blocked: bool = False,
        note: str = "",
        text: str = "",
    ) -> None:
        """记录"最近发送给对话用 LLM 的请求快照"（不区分模式，右下实时面板 + 落盘排障）。"""
        try:
            entry = {
                "time": utc_now(),
                "session_id": str(getattr(event, "unified_msg_origin", "") or ""),
                "user_name": self._safe_call(event, "get_sender_name"),
                "mode": mode,
                "blocked": bool(blocked),
                "system_prompt": str(system_prompt or "")[:4000],
                "prompt": str(prompt or "")[:2000],
                "text": str(text or "")[:600],
                "note": str(note or ""),
            }
            self.sent.record_sent(entry)
            # 0.167 快照落盘：sent_snapshot.json（滚动 30 条），供开发者/排障随时读最近实际发送内容
            try:
                import json as _json

                snap_path = Path(self.data_dir) / "sent_snapshot.json"
                history: list = []
                try:
                    if snap_path.exists():
                        raw = _json.loads(snap_path.read_text(encoding="utf-8"))
                        history = list(raw) if isinstance(raw, list) else []
                except Exception:
                    history = []
                history.append(entry)
                history = history[-30:]
                snap_path.write_text(
                    _json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8"
                )
            except Exception:
                pass
        except Exception:
            pass

    def _anchor_values(self, event: AstrMessageEvent) -> dict:
        """取各模块当前锚内容（放行注入的锚 + 接管模板的占位符内容统一来源）。"""
        values: dict = {}
        try:
            values["persona"] = (
                self.persona_store.injection_text()
                if self.config.bool("persona.enabled", True)
                else ""
            )
        except Exception:
            values["persona"] = ""
        try:
            values["current_user"] = self._current_user_label(event)
            values["place"] = self._place_label(event)
            values["identity"] = (
                self._build_identity_anchor(event) if self.config.bool("identity.enabled", True) else ""
            )
        except Exception:
            values["current_user"] = values.get("current_user", "")
            values["place"] = values.get("place", "")
            values["identity"] = ""
        try:
            voice = self.voice_store.load()
            values["voice"] = (
                build_voice_anchor(
                    voice,
                    place=self._place_label(event),
                    group_quiet=self.config.bool("voice.group_quiet", True),
                )
                if self.config.bool("voice.enabled", True)
                else ""
            )
        except Exception:
            values["voice"] = ""
        try:
            presence = self.presence_store.load()
            values["presence"] = build_presence_anchor(presence) if self.config.bool("presence.enabled", True) else ""
        except Exception:
            values["presence"] = ""
        try:
            schedule = self.schedule_store.load()
            values["schedule"] = (
                build_schedule_anchor(schedule, _hhmm()) if self.config.bool("schedule.enabled", True) else ""
            )
        except Exception:
            values["schedule"] = ""
        try:
            values["wardrobe"] = (
                build_wardrobe_anchor(self.wardrobe_store.current_outfit())
                if self.config.bool("wardrobe.enabled", True)
                else ""
            )
        except Exception:
            values["wardrobe"] = ""
        try:
            values["relationship"] = (
                build_relationship_anchor(
                    self.relationship_store.get(self._sender_id(event)),
                    presence,
                    memory_summary=self._relation_memory_summary(event),
                )
                if self.config.bool("relationship.enabled", True)
                else ""
            )
        except Exception:
            values["relationship"] = ""
        try:
            values["memory"] = self._recent_memory_hint(limit=6)
            values["weather"] = str(self.config.get("presence.weather", "") or "").strip()
            sightings = self.mind_store.all().get("sightings") or []
            values["mind"] = str(sightings[0].get("text") or "")[:120] if sightings else ""
            values["time"] = time.strftime("%Y-%m-%d %H:%M", time.localtime())
        except Exception:
            values["memory"] = ""
            values["weather"] = ""
            values["mind"] = ""
            values["time"] = ""
        # 0.183：{生图意愿} 占位符——生图侧产出的软标记（疑问式弱信号），10 分钟内生效
        try:
            session_id = str(getattr(event, "unified_msg_origin", "") or "")
            cached = self._image_wish_cache.get(session_id)
            if cached and time.time() - cached[1] <= 600:
                values["image_wish"] = cached[0]
            else:
                if cached:
                    self._image_wish_cache.pop(session_id, None)
                values["image_wish"] = ""
        except Exception:
            values["image_wish"] = ""
        return values

    def _current_user_label(self, event: AstrMessageEvent) -> str:
        """「当前和你对话的人」标签：昵称（ID）。"""
        sender = extract_sender(event)
        name = str(sender.get("user_name") or "").strip()
        pid = str(sender.get("user_id") or "").strip()
        if not name and not pid:
            return "（未知）"
        if name and pid:
            return f"{name}（{pid}）"
        return name or pid

    def _place_label(self, event: AstrMessageEvent) -> str:
        """「发送场合」标签：私聊 / 群聊。"""
        uid = str(getattr(event, "unified_msg_origin", "") or "")
        if "GroupMessage" in uid or "群" in uid:
            return "群聊"
        if "FriendMessage" in uid or "StrangerMessage" in uid:
            return "私聊"
        return "私聊" if not uid else "对话"

    def _recent_timeline_text(self, uid: str, limit: int = 4) -> str:
        """取该会话最近对话（【为你篆刻的历史】时间线）作为「{上下文}」注入内容。

        0.172：渲染时**按时间正序（旧→新）**，并给每行标注说话人（对方/我/系统/昵称）——
        此前无标注且时间线源返回最新在前，模型分不清谁说的、"你呢，吃了吗？"是谁在问（用户实测困惑）。
        需要联动记忆插件；未装载/取不到时返回空串（占位符替换为空，不阻塞接管发送）。
        """
        bridge = self._get_memory_bridge()
        if bridge is None:
            return ""
        try:
            getter = getattr(bridge, "get_timeline", None)
            if not callable(getter):
                return ""
            parts = str(uid or "").split(":")
            ctx: dict = {"session_id": str(uid or ""), "platform": parts[0] if parts else ""}
            events = list(getter(session_context=ctx, limit=limit) or [])
            from .timeline_filter import is_llm_context_event

            rows: list[tuple[str, str, str]] = []  # (time, label, text)
            for ev in events:
                if not is_llm_context_event(ev):
                    continue
                text = ""
                if isinstance(ev, dict):
                    text = str(ev.get("content") or ev.get("text") or "").strip()
                    role = str(ev.get("role") or "").lower()
                    name = str(ev.get("user_name") or ev.get("user_id") or "").strip()
                    ts = str(ev.get("occurred_at") or "")
                else:
                    text = str(getattr(ev, "content", "") or "").strip()
                    role = str(getattr(ev, "role", "") or "").lower()
                    name = str(getattr(ev, "user_name", "") or getattr(ev, "user_id", "") or "").strip()
                    ts = str(getattr(ev, "occurred_at", "") or "")
                if not text:
                    continue
                if role == "user":
                    label = name or "对方"
                elif role == "bot":
                    label = "我"
                else:
                    label = "系统"
                rows.append((ts, label, text[:100]))
            # 正序：时间线源一般最新在前——若首行时间晚于末行则反转
            if len(rows) >= 2:
                try:
                    if rows[0][0] and rows[-1][0] and rows[0][0] > rows[-1][0]:
                        rows = list(reversed(rows))
                except Exception:
                    pass
            return "\n".join(f"{label}：{text}" for _, label, text in rows)
        except Exception:
            return ""

    def _dedupe_current_message(self, context_text: str, current_msg: str) -> str:
        """从时间线文本中剔除当前轮消息（当前消息由 {当前说话}/【本次对话】承载，上下文里不应重复）。"""
        cur = str(current_msg or "").strip()
        if not cur:
            return str(context_text or "")
        try:
            lines = [ln.strip() for ln in str(context_text or "").split("\n") if ln.strip()]
            kept = [
                ln for ln in lines
                if not (ln == cur or (cur in ln and (len(ln) - len(cur)) <= 24))
            ]
            return "\n".join(kept)
        except Exception:
            return str(context_text or "")

    def _session_ctx_dict(self, event: AstrMessageEvent) -> dict:
        """由事件构造记忆插件需要的会话上下文 dict（尽力而为）。"""
        uid = str(getattr(event, "unified_msg_origin", "") or "")
        parts = uid.split(":") if uid else []
        sender = extract_sender(event)
        return {
            "session_id": uid,
            "platform": parts[0] if parts else "",
            "user_id": sender.get("user_id") or "",
            "user_name": sender.get("user_name") or "",
            "message_text": str(getattr(event, "message_str", "") or "")[:2000],
        }

    def _relation_memory_summary(self, event: AstrMessageEvent) -> str:
        """联动读取【为你篆刻的历史】的「约定/偏好/关系」记忆，作为 {关系} 锚的摘要。

        只读不写、不重复存储；未装载/取不到返回空串（锚里省略该段）。
        """
        bridge = self._get_memory_bridge()
        if bridge is None:
            return ""
        try:
            lister = getattr(bridge, "list_recent_memories", None)
            if not callable(lister):
                return ""
            ctx = self._session_ctx_dict(event)
            parts_text: list[str] = []
            for mtype in ("promise", "preference", "relationship"):
                try:
                    recs = lister(session_context=ctx, limit=3, memory_type=mtype)
                except Exception:
                    continue
                for rec in recs or []:
                    content = ""
                    if isinstance(rec, dict):
                        content = str(rec.get("content") or rec.get("summary") or "").strip()
                    elif hasattr(rec, "content"):
                        content = str(rec.content or "").strip()
                    elif hasattr(rec, "memory"):
                        content = str(getattr(rec.memory, "content", "") or getattr(rec.memory, "summary", "") or "").strip()
                    if not content:
                        content = str(rec or "").strip()
                    if content:
                        parts_text.append(content[:60])
            if not parts_text:
                return ""
            return "；".join(parts_text[:6])
        except Exception:
            return ""

    async def _compose_memory_text(self, event: AstrMessageEvent, fallback: str = "") -> str:
        """调用【为你篆刻的历史】compose_injection 生成完整记忆包（{记忆} 占位符）。

        接管绕过主链，记忆插件 on_llm_request 注入不触发；这里主动调用其注入合成接口。
        无联动/失败回退 fallback（轻量最近记忆）。
        """
        bridge = self._get_memory_bridge()
        if bridge is None:
            return fallback
        try:
            composer = getattr(bridge, "compose_injection", None)
            if not callable(composer):
                return fallback
            text = await composer(
                "当前对话的最近记忆与用户背景",
                session_context=self._session_ctx_dict(event),
                top_k=6,
                max_chars=1600,
            )
            return str(text or "").strip() or fallback
        except Exception:
            return fallback

    async def _archive_bot_reply_to_history(self, session_id: str, user_text: str, content: str) -> None:
        """接管改换：把本轮「用户消息 + Bot 回复」写进 AstrBot 会话历史（官方通道）。

        接管绕过主链（stop_event）→ AstrBot 主链的会话历史写入（agent 路径）不执行，
        下次用户消息走主链时上下文会缺这轮——这里补上（与 active 模式的 _archive_proactive_to_history 同机制）。
        尽力而为：取/建会话 + add_message_pair；失败静默（记忆时间线仍有回填兜底）。
        """
        session_id = str(session_id or "").strip()
        content = str(content or "").strip()
        user_text = str(user_text or "").strip()
        if not session_id or not content:
            return
        try:
            manager = getattr(self.context, "conversation_manager", None)
            if manager is None:
                return
            cid = ""
            getter = getattr(manager, "get_curr_conversation_id", None)
            if callable(getter):
                try:
                    cid = str(await getter(session_id) or "")
                except Exception:
                    cid = ""
            if not cid:
                creator = getattr(manager, "new_conversation", None)
                if not callable(creator):
                    return
                try:
                    cid = str(await creator(session_id, title="接管对话") or "")
                except TypeError:
                    cid = str(await creator(session_id) or "")
                except Exception:
                    return
            if not cid:
                return
            pair = getattr(manager, "add_message_pair", None)
            if not callable(pair):
                return
            await pair(
                cid,
                {"role": "user", "content": (user_text or "（对方没有说话）")[:2000]},
                {"role": "assistant", "content": content[:2000]},
            )
            logger.info("[Storyteller] 接管回复已写入会话历史: session=%s", session_id)
        except Exception as exc:
            logger.warning("[Storyteller] 接管回复写入会话历史失败: %s", exc)

    def _note_bot_reply(self, event: AstrMessageEvent, content: str) -> None:
        """把接管的 Bot 回复回填到记忆插件时间线（record_visible_turn role=bot）。

        否则接管绕过主链 → 记忆插件 on_llm_response 记录不到 Bot 回复，时间线缺 Bot 侧。
        尽力而为，失败静默。
        """
        content = str(content or "").strip()
        if not content:
            return
        bridge = self._get_memory_bridge()
        if bridge is None:
            return
        try:
            recorder = getattr(bridge, "record_visible_turn", None)
            if not callable(recorder):
                return
            asyncio.ensure_future(
                recorder(role="bot", content=content[:2000], session_context=self._session_ctx_dict(event))
            )
        except Exception:
            pass

    def _note_bot_reply_by_session(self, session_id: str, content: str) -> None:
        """发送缓冲每发一条 → 回填记忆插件时间线（role=bot，无 event 版）。

        与 _note_bot_reply 同机制，但只需要会话键（缓冲发送没有 event 对象）。
        """
        content = str(content or "").strip()
        session_id = str(session_id or "").strip()
        if not content or not session_id:
            return
        bridge = self._get_memory_bridge()
        if bridge is None:
            return
        try:
            recorder = getattr(bridge, "record_visible_turn", None)
            if not callable(recorder):
                return
            parts = session_id.split(":")
            ctx = {
                "session_id": session_id,
                "platform": parts[0] if parts else "",
                "scope": "private" if "FriendMessage" in session_id else "group",
                "user_id": (parts[2] if len(parts) > 2 and session_id.endswith(parts[2]) else ""),
                "group_id": (parts[2] if "GroupMessage" in session_id and len(parts) > 2 else ""),
            }
            asyncio.ensure_future(
                recorder(role="bot", content=content[:2000], session_context=ctx)
            )
        except Exception:
            pass

    def _note_proactive_sent(self, user: str, text: str) -> None:
        """主动消息发送成功 → 回填记忆插件时间线（role=bot），补上会话上下文缺口。

        主动消息走适配器直发（不经主链），记忆插件的 on_llm_response 记录不到；
        不回填则时间线缺 Bot 侧，阶段总结会断档。尽力而为，失败只记日志。
        """
        text = str(text or "").strip()
        if not text or not str(user or "").strip():
            return
        try:
            bridge = self._get_memory_bridge()
            if bridge is None:
                return
            recorder = getattr(bridge, "record_visible_turn", None)
            if not callable(recorder):
                return
            platform = str(
                self.config.get("proactive.session_platform", "aiocqhttp") or "aiocqhttp"
            ).strip() or "aiocqhttp"
            session_id = f"{platform}:FriendMessage:{user}"
            ctx = {
                "session_id": session_id,
                "platform": platform,
                "scope": "private",
                "user_id": str(user),
                "group_id": "",
            }
            asyncio.ensure_future(
                self._safe_record_bot_turn(recorder, text[:2000], ctx)
            )
            asyncio.ensure_future(self._archive_proactive_to_history(session_id, text))
        except Exception:
            pass

    async def _safe_record_bot_turn(self, recorder: Any, content: str, ctx: dict) -> None:
        try:
            await recorder(role="bot", content=content, session_context=ctx)
            logger.info(
                "[Storyteller] 主动消息已回填记忆时间线: session=%s",
                ctx.get("session_id") or "",
            )
        except Exception as exc:
            logger.warning("[Storyteller] 主动消息回填记忆时间线失败: %s", exc)

    async def _archive_proactive_to_history(self, session_id: str, text: str) -> None:
        """主动消息写入 AstrBot 会话历史（官方通道，等效「bot 发过主链消息」）。

        AstrBot 4.27 主链（会话 Main Agent）的 LLM 请求上下文直接读 conversation.history；
        发送后把「assistant=主动消息」写进当前会话，下次用户发言时主链上下文即可读到
        ——效果等同 bot 在主链里发过这句话，AstrBot 会话管理/WebUI 历史亦可见。
        由 proactive.archive_history 开关控制；conversation_manager 缺失/取会话失败/
        写失败一律静默（记忆时间线回填不受影响）。
        """
        if not self.config.bool("proactive.archive_history", True):
            return
        session_id = str(session_id or "").strip()
        text = str(text or "").strip()
        if not session_id or not text:
            return
        try:
            manager = getattr(self.context, "conversation_manager", None)
            if manager is None:
                return
            cid = ""
            getter = getattr(manager, "get_curr_conversation_id", None)
            if callable(getter):
                try:
                    cid = str(await getter(session_id) or "")
                except Exception:
                    cid = ""
            if not cid:
                creator = getattr(manager, "new_conversation", None)
                if not callable(creator):
                    return
                try:
                    cid = str(await creator(session_id, title="主动消息存档") or "")
                except TypeError:
                    # 旧版签名无 title 参数
                    cid = str(await creator(session_id) or "")
                except Exception:
                    return
            if not cid:
                return
            pair = getattr(manager, "add_message_pair", None)
            if not callable(pair):
                return
            await pair(
                cid,
                {"role": "user", "content": "[主动消息存档] 此刻并没有人说话，Bot 主动给用户发了一条消息，内容见 assistant 侧。"},
                {"role": "assistant", "content": text[:2000]},
            )
            logger.info("[Storyteller] 主动消息已写入会话历史: session=%s", session_id)
        except Exception as exc:
            logger.warning("[Storyteller] 主动消息写入会话历史失败: %s", exc)

    @staticmethod
    def _try_set_event_result(event: AstrMessageEvent, content: str) -> bool:
        """尽力把直连回复写回事件（尝试让 AstrBot 把它当作最终回复/计入会话历史）。

        不同 AstrBot 版本的 set_result 签名不同，失败静默；是否真计入历史以实机为准。
        """
        try:
            setter = getattr(event, "set_result", None)
            if not callable(setter):
                return False
            try:
                from astrbot.api.event import MessageEventResult as _MER

                obj: Any = _MER(content)
            except Exception:
                obj = content
            setter(obj)
            return True
        except Exception:
            return False

    async def _astrbot_default_persona(self) -> str:
        """兜底读取 AstrBot 当前默认人格 prompt（当 {人格} 注入体为空时用）。"""
        try:
            manager = getattr(self.context, "persona_manager", None)
            if manager is None:
                return ""
            getter = getattr(manager, "get_default_persona_v3", None)
            if not callable(getter):
                return ""
            try:
                result = getter(umo="")
            except TypeError:
                try:
                    result = getter()
                except TypeError:
                    result = None
            try:
                from inspect import isawaitable

                if isawaitable(result):
                    result = await asyncio.wait_for(result, timeout=2.0)
            except Exception:
                result = None
            if isinstance(result, dict):
                return str(result.get("prompt") or result.get("system_prompt") or result.get("content") or "").strip()
            if isinstance(result, str):
                return result.strip()
            if result is not None:
                for attr in ("prompt", "system_prompt", "content"):
                    try:
                        v = getattr(result, attr, None)
                    except Exception:
                        v = None
                    if v:
                        return str(v).strip()
            return ""
        except Exception:
            return ""

    async def _takeover_via_mainchain(
        self,
        event: AstrMessageEvent,
        req: ProviderRequest,
        user_text: str,
        prompt: str,
        system_prompt: str,
    ) -> None:
        """下次接管（走主链）：把模板结果写进主链即将发给 LLM 的请求并放行，回复走主链管线。

        - 主链来请求 → 我们拦截并把 `req.system_prompt` 替换为模板合成结果、`req.prompt` 改为引导句
          → 不 stop，交主链发出；LLM 回复会走 on_llm_response，记忆/二次润色/表情包/会话历史由主链管线接管。
        - 模型使用主链默认模型（不再需要独立的「接管改换模型」）。
        """
        try:
            from .intercept import replace_template

            session_id = str(getattr(event, "unified_msg_origin", "") or "")
            template = str(self.config.get("intercept.template", "") or "")
            anchors = self._anchor_values(event)
            anchors["current_text"] = prompt or user_text or "（对方没有说话）"
            anchors["context"] = self._recent_timeline_text(session_id, limit=4)
            # 0.163：时间线可能已含本轮消息（防抖收集时就写入了记忆插件时间线）——剔除，
            # 否则"你好？"在 {当前说话}/{上下文}/【本次对话】里重复多次，模型以为对方在重复发问
            anchors["context"] = self._dedupe_current_message(
                anchors["context"], str(prompt or user_text or "").strip()
            )
            # 走主链接管：保序脚本（媒体内嵌会意、位置保留）；异常/无组件链退化聚合 note（主链自己转图片）
            if self.config.bool("vision.enabled", True):
                try:
                    script = await build_ordered_media_script(self, event, with_llm=True)
                    if script:
                        anchors["current_text"] = script
                    else:
                        note = await build_media_note(
                            self, event, with_llm=True, max_chars=800,
                            include_images=False, include_face=False,
                        )
                        if note:
                            anchors["current_text"] = f"{anchors['current_text']}\n（对方这一轮还发了：{note}）"
                except Exception as exc:
                    logger.warning("[Storyteller] 走主链接管媒体会意失败: %s", exc)
            anchors["memory"] = _clean_memory_meta(
                await self._compose_memory_text(event, fallback=anchors.get("memory", ""))
            )
            if not anchors.get("persona", ""):
                anchors["persona"] = await self._astrbot_default_persona()
            # 0.159：上下文/记忆为空时直接留白（不注入占位句——占位句"没有更早的对话记录"反而
            # 诱导模型索要「设定/上下文」；防认错锚已不承诺"已含"，空白即正常）
            # 关系/风格为空时给中性占位（措辞不含"设定/上下文"字样）
            if not str(anchors.get("relationship") or "").strip():
                anchors["relationship"] = "（你和对方目前还不熟悉，保持礼貌与适当距离。）"
            if not str(anchors.get("voice") or "").strip():
                anchors["voice"] = "（还没定说话风格，自然表达即可。）"
            # 0.164：先给裸占位符内容加语义标签（治本，替代 0.162 末尾【本次对话】补丁——两遍一遍带标签一遍不带）
            anchors = _labelize_anchors(template, anchors)
            final_system = replace_template(template, anchors) or system_prompt
            # 0.158 模板健壮性：替换后仍残留标准占位符，或模板根本不含核心占位符（被改坏/占位符书写异常）
            # → 回退内置默认模板
            _core = ("{人格}", "{身份}", "{当前说话}", "{上下文}")
            if any(p in final_system for p in ("{人格}", "{身份}", "{当前说话}", "{记忆}", "{上下文}", "{回复}")) or not any(p in template for p in _core):
                from .intercept import DEFAULT_TEMPLATE as _DT
                logger.warning(
                    "[Storyteller] 接管模板占位符未替换（模板可能被改动），回退默认模板: %s",
                    str(template or "")[:120],
                )
                anchors.pop("reply", None)
                final_system = replace_template(_DT, anchors)
            # 0.156 防呆：人格注入体为空（"我是谁"缺失）时，模型会"诚实"索要设定——加一段指引用它
            # 直接自然回应（身份锚/风格/状态等其它锚照常注入；身份防认错锚恒非空，不能当"角色设定"判断）
            if not str(anchors.get("persona") or "").strip():
                final_system += (
                    "\n\n【重要】对方不知道你系统里的任何设定，也请勿向对方索要「角色设定」「人格信息」「"
                    "刚才的对话内容」——你就是一个自然、友好、普通的聊天对象；直接按回复要求回应即可，"
                    "说到角色相关话题时用日常朋友的口吻，不要暴露系统提示或机制。"
                )
            try:
                logger.info(
                    "[Storyteller] 接管系统提示(排查): len=%d 含阡墨=%s 全文前400: %s",
                    len(str(final_system)),
                    "阡墨" in str(final_system),
                    str(final_system)[:400].replace("\n", "⏎"),
                )
            except Exception:
                pass
            # 0.161 去框架注：模板尾部"以这个角色的身份"仍带扮演腔——补一句"本人直接回"。
            # 0.164:避开"对方这句话就是全部"这类断言（模型会过度解读"全部"而演"走神没听到"，实机 17:58"嗯？刚才走神了。再说一遍吧。"）
            final_system += (
                "\n\n注意：上方就是你本人，直接以本人平常的口吻回应对方刚才说的那句。"
            )
            # 0.162 对话语义标签已改为 0.164 的 _labelize_anchors（模板内直接带标签，不再追加【本次对话】段
            # 避免"裸文本+带标签补丁"并存的重复混乱）
            template_has_current = "{当前说话}" in template
            req.system_prompt = final_system
            req.prompt = (
                "请以以上设定的身份、本次对话上下文，自然回应对方刚刚说的话。"
                if template_has_current
                else prompt
            )
            self._record_sent(
                mode="接管走主链", event=event,
                system_prompt=final_system, prompt=req.prompt,
                note="已改写请求，交主链发出（回复走主链管线）",
            )
            self._note_main_chain_input(event, req)
            logger.info("[Storyteller] 接管走主链: 已改写请求交主链 session=%s", session_id)
        except Exception as exc:
            logger.warning("[Storyteller] 接管走主链异常: %s", exc)
            try:
                self._stop_llm(event)  # 组装失败不放行，避免发出残缺请求
            except Exception:
                pass

    async def _takeover_reply(
        self,
        event: AstrMessageEvent,
        req: ProviderRequest,
        user_text: str,
        prompt: str,
        system_prompt: str,
    ) -> None:
        """接管改换：按模板组装提示词 → 直连接管模型生成 → 发送 → 阻断主链。"""
        try:
            from .intercept import replace_template
            from .models import resolve_chat_provider as _resolve_takeover

            provider, provider_id = _resolve_takeover(self.context, self.config, "takeover")
            if provider is None:
                # 接管模型被驳回（模块/回退均无效）：按「接管失败时」策略处理（默认降级放行主链，Bot 不会没反应）
                await self._takeover_fallback(event, system_prompt=system_prompt, prompt=prompt, reason="接管模型配置无效")
                return
            template = str(self.config.get("intercept.template", "") or "")
            anchors = self._anchor_values(event)
            session_id = str(getattr(event, "unified_msg_origin", "") or "")
            # 「本次对话」注入：把防抖最终决定传给对话 LLM 的内容（当前说话）+ 上下文呼应喂进模板，
            # 由「拦＆改」统一整合发送（参考插件：所有功能注入完成后一次性发送）
            anchors["current_text"] = prompt or user_text or "（对方没有说话）"
            anchors["context"] = self._recent_timeline_text(session_id, limit=4)
            # 0.163：时间线可能已含本轮消息（防抖收集时就写入了记忆插件时间线）——剔除，
            # 否则"你好？"在 {当前说话}/{上下文}/【本次对话】里重复多次，模型以为对方在重复发问
            anchors["context"] = self._dedupe_current_message(
                anchors["context"], str(prompt or user_text or "").strip()
            )
            # 被抢话（B 方案）：把「没说完的话」作为上文注入，像被打断后重新组织语言
            buffer = getattr(self, "reply_buffer", None)
            if buffer is not None:
                try:
                    interrupted = buffer.take_interrupted_text(session_id)
                    if interrupted:
                        anchors["current_text"] = (
                            f"（你上一段话还没说完就被对方打断了——还没说完的是：{interrupted}\n"
                            f"现在对方又说了：{anchors['current_text']}）"
                        )
                except Exception:
                    pass
            # 组合消息会意（接管直连看不到 AstrBot 的附件注入）：保序脚本——媒体内嵌会意且保留原始位置
            # （"帮我看看这个/[文档]/算了不用了"顺序不再错位）；异常/无组件链退化聚合 note
            if self.config.bool("vision.enabled", True):
                try:
                    script = await build_ordered_media_script(self, event, with_llm=True)
                    if script:
                        anchors["current_text"] = script
                    else:
                        note = await build_media_note(self, event, with_llm=True, max_chars=800)
                        if note:
                            anchors["current_text"] = f"{anchors['current_text']}\n（对方这一轮还发了：{note}）"
                except Exception as exc:
                    logger.warning("[Storyteller] 接管媒体会意失败: %s", exc)
            # 记忆占位符升级：接管绕过主链，记忆插件 on_llm_request 注入不触发——用 compose_injection
            # 生成完整记忆包（含当前发言者/召回记忆）替换 {记忆}；无联动/失败回退轻量最近记忆
            anchors["memory"] = _clean_memory_meta(
                await self._compose_memory_text(event, fallback=anchors.get("memory", ""))
            )
            if not anchors.get("persona", ""):
                anchors["persona"] = await self._astrbot_default_persona()
            # 0.159：上下文/记忆为空时直接留白（不注入占位句——占位句"没有更早的对话记录"反而
            # 诱导模型索要「设定/上下文」；防认错锚已不承诺"已含"，空白即正常）
            # 关系/风格为空时给中性占位（措辞不含"设定/上下文"字样）
            if not str(anchors.get("relationship") or "").strip():
                anchors["relationship"] = "（你和对方目前还不熟悉，保持礼貌与适当距离。）"
            if not str(anchors.get("voice") or "").strip():
                anchors["voice"] = "（还没定说话风格，自然表达即可。）"
            # 0.164：先给裸占位符内容加语义标签（治本，替代 0.162 末尾【本次对话】补丁——两遍一遍带标签一遍不带）
            anchors = _labelize_anchors(template, anchors)
            final_system = replace_template(template, anchors) or system_prompt
            # 0.158 模板健壮性：替换后仍残留标准占位符，或模板根本不含核心占位符（被改坏/占位符书写异常）
            # → 回退内置默认模板
            _core = ("{人格}", "{身份}", "{当前说话}", "{上下文}")
            if any(p in final_system for p in ("{人格}", "{身份}", "{当前说话}", "{记忆}", "{上下文}", "{回复}")) or not any(p in template for p in _core):
                from .intercept import DEFAULT_TEMPLATE as _DT
                logger.warning(
                    "[Storyteller] 接管模板占位符未替换（模板可能被改动），回退默认模板: %s",
                    str(template or "")[:120],
                )
                anchors.pop("reply", None)
                final_system = replace_template(_DT, anchors)
            # 0.156 防呆：人格注入体为空（"我是谁"缺失）时，模型会"诚实"索要设定——加一段指引用它
            # 直接自然回应（身份锚/风格/状态等其它锚照常注入；身份防认错锚恒非空，不能当"角色设定"判断）
            if not str(anchors.get("persona") or "").strip():
                final_system += (
                    "\n\n【重要】对方不知道你系统里的任何设定，也请勿向对方索要「角色设定」「人格信息」「"
                    "刚才的对话内容」——你就是一个自然、友好、普通的聊天对象；直接按回复要求回应即可，"
                    "说到角色相关话题时用日常朋友的口吻，不要暴露系统提示或机制。"
                )
            try:
                logger.info(
                    "[Storyteller] 接管系统提示(排查): len=%d 含阡墨=%s 全文前400: %s",
                    len(str(final_system)),
                    "阡墨" in str(final_system),
                    str(final_system)[:400].replace("\n", "⏎"),
                )
            except Exception:
                pass
            # 0.161 去框架注：模板尾部"以这个角色的身份"仍带扮演腔——补一句"本人直接回"。
            # 0.164:避开"对方这句话就是全部"这类断言（模型会过度解读"全部"而演"走神没听到"，实机 17:58"嗯？刚才走神了。再说一遍吧。"）
            final_system += (
                "\n\n注意：上方就是你本人，直接以本人平常的口吻回应对方刚才说的那句。"
            )
            # 0.162 对话语义标签已改为 0.164 的 _labelize_anchors（模板内直接带标签，不再追加【本次对话】段
            # 避免"裸文本+带标签补丁"并存的重复混乱）
            # 0.165 格式工整：注入后压缩连续空行（{记忆}/{天气}/{见闻} 空时模板会留出多个空行连排）
            try:
                import re as _re
                final_system = _re.sub(r"\n{3,}", "\n\n", str(final_system or ""))
            except Exception:
                pass
            # 0.168 连发接住：对方一句话内连续输入多条（如"hmmm/这么冷淡/你在干嘛"合并），
            # 模型易只挑情绪重的一句、漏掉问句——补一句"都接住，先回最后的问句"
            try:
                _lines = [
                    ln.strip() for ln in str(anchors.get("current_text") or "").split("\n")
                    if ln.strip() and not ln.strip().startswith("【")
                ]
                if len(_lines) >= 2:
                    final_system += (
                        "\n\n【连发的习惯】对方这一条里连着说了上面几句——都接住；"
                        "如果最后一句是问句，先回答它。"
                    )
            except Exception:
                pass
            # 模板已含「当前说话」：不再把原文重复作为独立 prompt（防抖最终内容已注入模板），用简短引导
            # 0.161: 引导句不提「设定/身份/上下文」——这些词会被模型转引成索要话术（实机证据:模型引用"以上设定"）
            template_has_current = "{当前说话}" in template
            send_prompt = (
                "直接回应对方刚刚说的话，像平时聊天一样。"
                if template_has_current
                else prompt
            )
            # 兼容：部分 AstrBot/provider 的 text_chat 不接受 system_prompt 命名参数，
            # 此时把模板内容拼到 prompt 头部，避免 TypeError 导致接管永久静默阻断
            accept_sys = self._text_chat_accepts_system_prompt(provider)
            call_kwargs: dict = {}
            call_prompt = send_prompt
            if accept_sys and final_system:
                call_kwargs["system_prompt"] = final_system
            elif not accept_sys and final_system:
                call_prompt = f"{final_system}\n\n{send_prompt}".strip()
            # 接管回复属创作（要拟人、要走心）：保留模型思考
            call_kwargs["_disable_thinking"] = False
            try:
                from astrbot.api.event import MessageChain

                resp = await asyncio.wait_for(
                    chat_text(
                        provider,
                        self.config,
                        prompt=call_prompt,
                        session_id=f"storyteller_takeover:{getattr(event, 'unified_msg_origin', '')}",
                        **call_kwargs,
                    ),
                    timeout=90,
                )
                if not str(getattr(resp, "completion_text", "") or "").strip():
                    raise RuntimeError("接管生成返回空内容")
            except (asyncio.TimeoutError, Exception) as exc:
                logger.warning("[Storyteller] 接管改换: 生成失败/超时: %s", exc)
                # 按「接管失败时」策略：默认降级放行主链（原行为为静默阻断 + 直发文案）
                await self._takeover_fallback(event, system_prompt=final_system, prompt=prompt, reason=f"生成失败/超时: {exc}")
                return
            self._record_usage(resp, "takeover", provider_id or "default")
            content = str(getattr(resp, "completion_text", "") or "").strip()
            try:
                logger.info("[Storyteller] 接管生成内容: len=%d %s", len(content), content[:120].replace("\n", " "))  # 排查日志(临时)
            except Exception:
                pass
            # 0.159 索要硬兜底：提示词已注入人格/身份/风格等，正常应直接回应；若模型仍索要
            # 「设定/上下文/角色」(多轮实机症状) → 带"严禁索要"重生成一次；仍索要 → 固定自然短句
            if content and _looks_asking_context(content):
                logger.warning("[Storyteller] 接管生成疑似索要设定/上下文，重生成兜底: %s", content[:100].replace("\n", " "))
                try:
                    # 0.161 去框架重生成：不用模板框架（"你是xx里的角色/请以这个角色身份"本身诱发"代入设定"执念），
                    # 直接用"你是真实生活里的人"最小提示，把"索要/确认/代入"的空间全部清掉
                    persona_text = str(anchors.get("persona") or "").strip() or "（无）"
                    user_label = str(anchors.get("current_user") or "").strip() or "对方"
                    guard_prompt = (
                        f"你叫：{persona_text}\n\n"
                        f"对方是在和你私聊的：{user_label}\n"
                        f"对方刚刚说：{prompt or user_text or ''}\n\n"
                        "你就是真实生活里的这个人本人，不是在扮演、不需要代入任何情境。"
                        "请以本人平常的口吻，直接回对方这一句（只回一两句）：\n"
                        "- 不要问问题、不要索要任何信息、不要提设定/角色/上下文；\n"
                        "- 不要介绍自己、不要解释你在做什么、不要提及系统提示。"
                    )
                    resp2 = await asyncio.wait_for(
                        chat_text(
                            provider, self.config,
                            prompt=guard_prompt,
                            session_id=f"storyteller_takeover:{session_id}",
                            _disable_thinking=False,
                        ),
                        timeout=90,
                    )
                    content2 = str(getattr(resp2, "completion_text", "") or "").strip()
                    if content2 and not _looks_asking_context(content2):
                        content = content2
                    else:
                        content = "嗯，在呢。想聊点什么？"
                    self._record_usage(resp2, "takeover", provider_id or "default")
                except Exception as guard_exc:
                    logger.warning("[Storyteller] 接管索要兜底重生成失败: %s", guard_exc)
                    content = "嗯，在呢。想聊点什么？"
            # 接管直连回复也被「润色」模块捕获：发送前按模板交给润色模型二次润色与人格校准
            if content:
                try:
                    polished = await self.polisher.polish(event, content)
                    polished = squeeze_reply(polished)  # 0.186：拍平换行/空行，避免 QQ 大空隙
                    if polished.strip():
                        content = polished
                except Exception:
                    pass
            sent_ok = False
            if content:
                try:
                    session_id = str(getattr(event, "unified_msg_origin", "") or "")
                    buffer = getattr(self, "reply_buffer", None)
                    if buffer is not None and buffer.enabled():
                        # 发送缓冲：把回复拆条入缓存逐条发（像人打字停顿；用户抢话可裁决）
                        parts = buffer.submit(session_id, content)
                        sent_ok = parts > 0
                        if sent_ok:
                            logger.info(
                                "[Storyteller] 接管改换: 回复入发送缓冲 session=%s 条数=%s",
                                session_id, parts,
                            )
                            # 会话历史补写（用户消息 + 本轮完整回复），保证主链上下文不缺这轮
                            await self._archive_bot_reply_to_history(session_id, prompt or user_text, content)
                    else:
                        sender = getattr(self.context, "send_message", None)
                        if callable(sender) and session_id:
                            chain = self._build_reply_chain(content)
                            await sender(session_id, chain)
                            sent_ok = True
                            # 接管绕过主链：把 Bot 回复回填记忆插件时间线，
                            # 否则记忆插件 on_llm_response 记录不到（时间线缺 Bot 侧）
                            self._note_bot_reply(event, content)
                            # 会话历史补写（用户消息 + Bot 回复）
                            await self._archive_bot_reply_to_history(session_id, prompt or user_text, content)
                            # 尽力把直连回复写回事件（尝试计入 AstrBot 会话历史，实机验证）
                            self._try_set_event_result(event, content)
                            logger.info(
                                "[Storyteller] 接管改换: 已生成并发送回复 session=%s len=%s",
                                session_id, len(content),
                            )
                except Exception as exc:
                    logger.warning("[Storyteller] 接管改换: 发送失败: %s", exc)
            self._stop_llm(event)  # 无论成功与否都阻断主链，防止双重回复
            self._record_sent(
                mode="接管改换", event=event,
                system_prompt=final_system, prompt=prompt,
                blocked=not sent_ok, text=content,
                note="已接管生成并发送" if sent_ok else "接管生成但发送失败",
            )
        except Exception as exc:
            logger.warning("[Storyteller] 接管改换异常: %s", exc)
            self._stop_llm(event)
            try:
                self._record_sent(
                    mode="接管改换", event=event,
                    system_prompt=locals().get("final_system", ""),
                    prompt=locals().get("prompt", ""),
                    blocked=True, note="接管处理异常，已静默阻断",
                )
            except Exception:
                pass

    def _text_chat_accepts_system_prompt(self, provider: Any) -> bool:
        """探测 provider.text_chat 是否接受 system_prompt 命名参数（兼容不同 AstrBot/provider 版本）。

        无法探测时按接受处理（维持原有传参行为）。
        """
        try:
            import inspect

            sig = inspect.signature(getattr(provider, "text_chat"))
            params = sig.parameters
            if "system_prompt" in params:
                return True
            return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        except Exception:
            return True

    def _build_reply_chain(self, content: str, *, user: str = "") -> Any:
        """构造发送链；含表情包占位符时渲染为文本+图片（与主链 on_llm_response 一致）。"""
        from astrbot.api.event import MessageChain

        emoji_store = getattr(self, "emoji_store", None)
        if emoji_store is not None:
            try:
                if callable(getattr(emoji_store, "has_placeholder", None)) and emoji_store.has_placeholder(content):
                    days = max(0, int(self.config.int("emoji.duplicate_days", 3) or 3))
                    segments = emoji_store.render(content, dedup_days=days, user=user)
                    chain = MessageChain()
                    for seg in segments:
                        if seg.get("type") == "text" and seg.get("content"):
                            chain.message(seg["content"])
                        elif seg.get("type") == "emoji":
                            try:
                                chain.file_image(seg.get("path"))
                            except Exception:
                                pass
                    return chain
            except Exception:
                pass
        return MessageChain().message(content)
    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, resp: Any):
        """主链 LLM 回复后：Token 记账（主链真实调用）+ 二次润色 + 智能判定 + 表情包占位符渲染。"""
        # 主链真实调用的 token 记账（不受回复链路开关影响；接管改换不触发本事件）
        try:
            self._record_astr_total(event, resp)
        except Exception:
            pass
        try:
            self._record_main_chain_usage(event, resp)
        except Exception:
            pass
        if not self.config.bool("pipeline.enabled", True):
            return
        try:
            final_text = await self.reply_pipeline.process(event, resp)
            if self.emoji_store.has_placeholder(final_text):
                # 渲染表情包占位符 → 组装 MessageChain（文本 + 图片）
                from astrbot.api.event import MessageChain

                user = ""
                try:
                    from .persona import extract_sender

                    user = extract_sender(event).get("user_id") or ""
                except Exception:
                    pass
                days = max(0, int(self.config.int("emoji.duplicate_days", 3) or 3))
                segments = self.emoji_store.render(final_text, dedup_days=days, user=user)
                chain = MessageChain()
                for seg in segments:
                    if seg["type"] == "text" and seg["content"]:
                        chain.message(seg["content"])
                    elif seg["type"] == "emoji":
                        try:
                            chain.file_image(seg["path"])
                        except Exception:
                            pass
                resp.result_chain = chain
                resp.completion_text = ""
                logger.info(
                    "[Storyteller] 已渲染表情包: session=%s segs=%s",
                    getattr(event, "unified_msg_origin", ""), len(segments),
                )
            else:
                resp.completion_text = final_text
        except Exception as exc:
            logger.warning("[Storyteller] 回复链路处理异常: %s", exc)

    # ------------------------------------------------------------ 记忆联动

    def _import_deepmemory_bridge_module(self) -> Any:
        """导入【为你篆刻的历史】的桥接模块（双路径）。

        AstrBot v4 以 data.plugins.<插件名> 命名空间加载插件（core 目录在 sys.path），
        顶层包名 astrbot_plugin_deepmemory 并不可导入；旧版 AstrBot / 开发桩环境
        用顶层包名。因此优先 data.plugins 路径，失败回退顶层路径。
        全部失败返回 None，并记录原因供面板展示（不再静默吞错）。
        """
        for import_path in (
            "data.plugins.astrbot_plugin_deepmemory.core.bridge",
            "astrbot_plugin_deepmemory.core.bridge",
        ):
            try:
                return importlib.import_module(import_path)
            except Exception as exc:
                continue
        return None

    def _get_memory_bridge(self) -> Any:
        try:
            module = self._import_deepmemory_bridge_module()
            if module is None:
                return None
            fetcher = getattr(module, "get_deepmemory_bridge", None)
            if not callable(fetcher):
                return None
            return fetcher()
        except Exception:
            return None

    def _memory_bridge_status(self) -> dict:
        """记忆联动识别接口：分级诊断（未安装/已加载但桥接未启/正常），供页面展示。"""
        module = None
        import_error = ""
        for import_path in (
            "data.plugins.astrbot_plugin_deepmemory.core.bridge",
            "astrbot_plugin_deepmemory.core.bridge",
        ):
            try:
                module = importlib.import_module(import_path)
                break
            except Exception as exc:
                import_error = f"{import_path}: {exc}"
        if module is None:
            return {
                "available": False,
                "installed": False,
                "reason": "未检测到【为你篆刻的历史】插件（未安装或尚未加载）",
                "detail": import_error[:200],
            }
        fetcher = getattr(module, "get_deepmemory_bridge", None)
        bridge = fetcher() if callable(fetcher) else None
        if bridge is None:
            return {
                "available": False,
                "installed": True,
                "reason": "【为你篆刻的历史】已运行，但协同桥接不可用：请在它的设置页确认「插件协同桥接 → 启用桥接 API」已开启，然后重载插件",
                "detail": "bridge object is None（桥接开关关闭或插件未完成初始化）",
            }
        status = {
            "available": True,
            "installed": True,
            "reason": "联动正常",
            "detail": "",
        }
        try:
            reporter = getattr(bridge, "bridge_status", None)
            if callable(reporter):
                extra = reporter()
                if isinstance(extra, dict):
                    status.update(extra)
        except Exception:
            pass
        return status

    @staticmethod
    def _is_self_message(event: Any) -> bool:
        """识别平台回显的「机器人自己发出的消息」（sender == 自身 ID）。

        部分 OneBot 实现会把 Bot 发出的消息作为 message 事件回传；若不识别，
        会被当成对方消息处理（观察/捕获/回复自己）。默认平台不上报，此为双保险。
        """
        try:
            self_id = getattr(event, "get_self_id", None)
            sender_id = getattr(event, "get_sender_id", None)
            if callable(self_id) and callable(sender_id):
                sid = str(self_id() or "")
                uid = str(sender_id() or "")
                if sid and uid:
                    return sid == uid
            message_obj = getattr(event, "message_obj", None)
            if message_obj is not None:
                obj_self = str(getattr(message_obj, "self_id", "") or "")
                sender = getattr(message_obj, "sender", None)
                obj_sender = str(getattr(sender, "user_id", "") or "") if sender is not None else ""
                if obj_self and obj_sender:
                    return obj_self == obj_sender
        except Exception:
            pass
        return False

    def _sync_memory_managed(self, enable: bool) -> None:
        """按「本次请求是否由本插件托管注入记忆」动态同步记忆插件的自动注入状态。

        修复（0.146）：旧实现无条件托管，导致「拦截关闭 / 监视 / 阻断 / 接管改换」下
        记忆插件自动注入被关闭、而本插件又不注入 → 主链请求完全拿不到记忆。
        现在：
        - 本插件将注入（放行 / 接管走主链）→ enable=True：记忆插件跳过自动注入，避免双份；
        - 本插件不注入（监视 / 阻断 / 命令 / 拦截关闭 / 用户关闭托管开关）→ enable=False：
          恢复记忆插件自动注入（其发起的主链请求照常带记忆）。
        状态无变化时不重复调用桥接；记忆插件缺失时保持未同步，后续事件自动重试。
        """
        try:
            if not self.config.bool("memory.managed_injection", True):
                enable = False
            if enable == self._memory_managed_active and self._memory_managed_checked:
                return
            bridge = self._get_memory_bridge()
            if bridge is None:
                return  # 记忆插件未装/桥未开：无需托管（保持未同步，后续事件重试）
            setter = getattr(bridge, "set_injection_managed", None)
            if callable(setter):
                setter(enable)
                self._memory_managed_active = bool(enable)
                self._memory_managed_checked = True
                logger.info("[Storyteller] 记忆注入托管同步: managed=%s", enable)
        except Exception as exc:
            logger.warning("[Storyteller] 记忆注入托管同步失败: %s", exc)

    async def _inject_memory(self, bridge: Any, event: AstrMessageEvent, req: ProviderRequest) -> bool:
        try:
            injector = getattr(bridge, "inject_for_event", None)
            if callable(injector):
                return bool(await injector(req, event))
        except Exception as exc:
            logger.warning("[Storyteller] 托管注入记忆失败: %s", exc)
        return False

    # ------------------------------------------------------------ 观察 / 记忆写入

    def _mark_praised_outfit(self, text: str) -> None:
        """0.151：用户夸奖当前穿搭（好看/漂亮/喜欢… + 衣服词）→ 把穿搭里的衣物标记为重要。

        重要衣物（important/manual）优先展示且不会被「一键置换衣柜」清空，只能手动删除。
        """
        if not re.search(r"好看|漂亮|不错|喜欢|可爱|帅气|好美|美|好看呀|好棒", text):
            return
        if not re.search(r"衣服|穿搭|裙子|外套|上衣|鞋|裤子|打扮|穿得|这身|今天穿的|连衣裙|衬衫", text):
            return
        outfit = self.wardrobe_store.current_outfit()
        items = [str(x).strip() for x in (outfit.get("items") or []) if str(x).strip()]
        if not items:
            return
        logger.info("[Storyteller] 用户夸奖当前穿搭，标记重要: %s", "、".join(items[:4]))
        self.wardrobe_store.mark_names(items[:8])

    def _observe_message(self, event: AstrMessageEvent) -> None:
        """收集画像素材 + 检测情绪余波/约定愿望 + 媒体互动信号（异步处理）。"""
        text = str(getattr(event, "message_str", "") or "").strip()
        self._observe_media(event, text)
        # 表情包 opt-out / opt-in：用户明说「别发表情包」→ 关闭；「可以发表情」→ 重开
        try:
            self._detect_emoji_preference(event, text)
        except Exception:
            pass
        # 0.151：用户夸奖 Bot 当前穿搭的衣物 → 标记重要（不会被一键置换清空）
        try:
            self._mark_praised_outfit(text)
        except Exception:
            pass
        if not text:
            return
        if detect_profile(text) or detect_commitment(text):
            self._profile_buffer.append(
                {"text": text[:300], "ctx": build_session_context(event)}
            )
            if len(self._profile_buffer) > 200:
                self._profile_buffer = self._profile_buffer[-200:]
            if len(self._profile_buffer) >= 20:
                asyncio.ensure_future(self._flush_profile())
        # 情绪余波：用户表露明显情绪时记录 + 即时微调情绪维度（节流；受「轻量事件演化」总开关控制）
        emotion = self._detect_emotion(text)
        if emotion and self.config.bool("presence.light_evolve_enabled", True):
            self._emotion_buffer.append(emotion)
            if len(self._emotion_buffer) > 12:
                self._emotion_buffer = self._emotion_buffer[-12:]
            now_ts = time.monotonic()
            stain_interval = max(1, self.config.int("presence.stain_interval", 5)) * 60
            if now_ts - self._last_emotion_refresh > stain_interval:
                self._last_emotion_refresh = now_ts
                self._apply_emotion_impulse(text)
                if self.config.bool("presence.enabled", True) and self.config.bool("presence.auto_refresh", False):
                    pass  # 情绪染色本身即轻量事件演化；大演化交给节拍
        if detect_commitment(text) and self.config.bool("memory.commitment_enabled", True):
            asyncio.ensure_future(self._write_commitment(event, text))
        # 实时日程/穿搭调整：对话里出现明确安排 → 像人一样决定改不改（检测门槛即闸门，不每句判定）
        try:
            plan_kind = self._detect_plan_intent(text)
            if plan_kind:
                asyncio.ensure_future(self._auto_plan(event, plan_kind, text))
        except Exception:
            pass
        # 互动积累：达到阈值后由 LLM 精确判断关系变化并提炼「最近印象」（阈值可配）
        sender_id = extract_sender(event).get("user_id") or ""
        if sender_id:
            batch = max(3, self.config.int("relationship.impression_batch", 10))
            buf = self._interaction_buffer.setdefault(sender_id, [])
            buf.append(text[:200])
            if len(buf) > 100:
                del buf[: len(buf) - 100]
            if len(buf) >= batch:
                self._interaction_buffer[sender_id] = []
                asyncio.ensure_future(self._judge_relationship(sender_id, list(buf)))
        # 状态节拍懒触发：自动演化开启且到节拍间隔 → 后台演化（像人慢慢缓过来，不常驻定时器）
        try:
            if self.config.bool("presence.auto_refresh", False):
                interval = max(5, self.config.int("presence.beat_interval", 30)) * 60
                if time.time() - self._last_presence_beat >= interval:
                    self._last_presence_beat = time.time()
                    asyncio.ensure_future(self._refresh_presence(event=event))
        except Exception:
            pass

    # ------------------------------------------------------------ 实时日程/穿搭调整（像人）

    @staticmethod
    def _detect_plan_intent(text: str) -> str:
        """轻量检测「对话里出现了明确的日程/穿搭安排」。

        返回 ""（不需要决策）或 "schedule" / "outfit"（命中哪种安排）。
        检测门槛本身即闸门：只有明确的安排才触发决策，不会每句话都判定。
        询问/疑问语气（…吗？/什么安排？）不算安排，不触发。
        """
        t = (text or "").strip()
        if len(t) < 4:
            return ""
        # 疑问/询问语气不触发（对话里问"你有什么安排吗"不是给安排）
        if t.endswith("吗") or t.endswith("？") or t.endswith("?") or "什么安排" in t or "安排吗" in t or "有没有" in t and "安排" in t:
            return ""
        # 穿搭类：明确说穿什么/换衣服/别穿某件/衣柜/哪件
        outfit_kw = ("穿什么", "穿哪件", "换衣服", "换件", "别穿", "穿这件", "穿那件", "换上", "衣柜里", "穿这件吧", "穿那件吧", "不用穿", "换成")
        if any(w in t for w in outfit_kw):
            return "outfit"
        # 衣柜类：明确说给你买了新衣服/送你一件/衣柜里添
        closet_kw = ("新衣服", "给你买了", "送你的", "给你买了件", "给你添了", "衣柜里加", "衣柜里放", "收纳了", "买了件", "给你买了套", "寄给你的")
        if any(w in t for w in closet_kw):
            return "closet"
        # 日程类：时间词 + 安排词（缺一不可，避免闲聊误触）
        time_kw = ("明天", "后天", "今晚", "今天", "下午", "上午", "晚上", "早上", "中午", "点钟", "点 ", "点，", "点。", "小时", "周", "周一", "周二", "周三", "周四", "周五", "周六", "周日", "改到", "推迟到", "提前到")
        plan_kw = ("安排", "计划", "约", "陪我去", "一起去", "记得", "别忘了", "要去做", "得去", "改成", "改到", "推迟", "取消", "改期", "重排", "来不了了", "空出来", "腾出", "排", "日程", "定在", "定好", "约好", "见", "吃饭", "看电影", "锻炼", "健身", "上班", "开会")
        if any(w in t for w in time_kw) and any(w in t for w in plan_kw):
            return "schedule"
        return ""

    async def _auto_plan(self, event: AstrMessageEvent, kind: str, text: str) -> None:
        """调日程/穿搭模型做一次「像人」的决策并落库（异步；失败静默，不阻塞对话）。"""
        try:
            from .schedule import apply_auto_plan, build_auto_plan_prompt, parse_schedule
            from .models import resolve_chat_provider

            if not self.config.bool("schedule.auto_manage_enabled", True):
                return
            provider, provider_id = resolve_chat_provider(self.context, self.config, "schedule")
            if provider is None:
                logger.info("[Storyteller] 实时调整跳过：无可用日程模型（可用「日程 → 日程模型」或回退策略配置）")
                return
            schedule = self.schedule_store.load()
            outfit = self.wardrobe_store.current_outfit() if hasattr(self, "wardrobe_store") else {}
            closet = self.wardrobe_store.closet_items() if hasattr(self, "wardrobe_store") else []
            prompt = build_auto_plan_prompt(
                user_text=text, schedule=schedule, outfit=outfit, closet=closet
            )
            resp = await chat_text(provider, self.config, prompt=prompt, session_id="storyteller_auto_plan")
            self._record_usage(resp, "schedule", provider_id or "default")
            decision = parse_schedule(str(getattr(resp, "completion_text", "") or ""))
            if not decision:
                logger.info("[Storyteller] 实时调整跳过：模型未返回有效 JSON")
                return
            result = apply_auto_plan(decision, self.schedule_store, self.wardrobe_store)
            if result.get("applied"):
                logger.info("[Storyteller] 实时调整: kind=%s %s", kind, result.get("summary", ""))
            else:
                logger.info("[Storyteller] 实时调整: 判定不需要改动（%s）", result.get("summary", ""))
        except Exception as exc:
            logger.warning("[Storyteller] 实时调整失败: %s", exc)

    # ------------------------------------------------------------ 实时日程/穿搭调整（像人）end

    @staticmethod
    def _detect_emotion(text: str) -> str:
        """轻量检测用户消息里的情绪，返回情绪标签（无则空串）。"""
        t = (text or "").strip()
        if not t:
            return ""
        joy = ("开心", "高兴", "太好了", "好耶", "哈哈", "哈哈哈", "笑死", "棒", "爱了", "幸福")
        sad = ("难过", "伤心", "哭", "委屈", "低落", "丧", "emo", "崩溃", "难受", "心疼")
        angry = ("生气", "气死", "烦", "火大", "无语", "恼", "讨厌")
        tired = ("累", "困", "疲惫", "没精神", "撑不住")
        if any(w in t for w in joy):
            return f"对方很开心：{t[:60]}"
        if any(w in t for w in sad):
            return f"对方情绪低落：{t[:60]}"
        if any(w in t for w in angry):
            return f"对方有点烦躁：{t[:60]}"
        if any(w in t for w in tired):
            return f"对方说累了：{t[:60]}"
        return ""

    def _apply_emotion_impulse(self, text: str) -> None:
        """用户情绪事件即时微调 Bot 心绪（染色一笔 + 涟漪余光），带自然节拍回落。"""
        if not self.config.bool("presence.light_evolve_enabled", True):
            return
        try:
            from .presence import stain

            presence = self.presence_store.load(with_decay=False)
            t = (text or "").strip()
            adjusted = False
            kind = ""
            if any(w in t for w in ("开心", "高兴", "太好了", "好耶", "哈哈", "笑死", "棒", "爱了", "幸福")):
                kind = "分享"
            elif any(w in t for w in ("难过", "伤心", "哭", "委屈", "低落", "丧", "emo", "崩溃", "难受", "心疼")):
                kind = "求助"
            elif any(w in t for w in ("生气", "气死", "火大", "恼", "无语")):
                kind = "争执"
            if kind:
                if "道谢" in t or any(w in t for w in ("谢谢", "谢啦", "感谢", "爱你哦", "爱你嗷")):
                    kind = "道谢"
                if self.config.bool("presence.ripple_enabled", True):
                    presence = stain(presence, kind, text=t[:40])
                else:
                    from .presence import clamp

                    presence["tone"] = clamp(presence.get("tone", 0.0) + (0.12 if kind in ("分享", "道谢") else -0.12), -1.0, 1.0)
                    presence["tempo"] = clamp(presence.get("tempo", 0.0) + (0.06 if kind in ("分享", "争执") else -0.04), -1.0, 1.0)
                adjusted = True
            if adjusted:
                presence["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                self.presence_store.save(presence)
                logger.info(
                    "[Storyteller] 情绪染色: kind=%s mood=%s tone=%.2f tempo=%.2f ripples=%s",
                    kind, presence.get("mood", ""), presence.get("tone", 0),
                    presence.get("tempo", 0), len(presence.get("ripples") or []),
                )
        except Exception:
            pass

    def _note_proactive_unanswered(self, user: str) -> None:
        """主动消息被晾着：Bot 心情微降一档（规则染色，不调 LLM）。"""
        if not self.config.bool("presence.light_evolve_enabled", True):
            return
        try:
            from .presence import stain

            presence = self.presence_store.load(with_decay=False)
            presence = stain(presence, "冷落", text="自己发的消息一直没回")
            presence["tone"] = max(-1.0, float(presence.get("tone", 0.0)) - 0.06)
            presence["tempo"] = max(-1.0, float(presence.get("tempo", 0.0)) - 0.04)
            presence["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            self.presence_store.save(presence)
            logger.info(
                "[Storyteller] 未回应心情微降: user=%s tone=%.2f mood=%s",
                user, presence.get("tone", 0), presence.get("mood", ""),
            )
        except Exception:
            pass

    def _note_proactive_replied(self, user: str) -> None:
        """对方终于回话了：心情回升一档（规则染色，不调 LLM）。"""
        if not self.config.bool("presence.light_evolve_enabled", True):
            return
        try:
            from .presence import stain

            presence = self.presence_store.load(with_decay=False)
            presence = stain(presence, "回应", text="对方终于回话了")
            presence["tone"] = min(1.0, float(presence.get("tone", 0.0)) + 0.06)
            presence["tempo"] = min(1.0, float(presence.get("tempo", 0.0)) + 0.02)
            presence["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            self.presence_store.save(presence)
            logger.info(
                "[Storyteller] 回应心情回升: user=%s tone=%.2f mood=%s",
                user, presence.get("tone", 0), presence.get("mood", ""),
            )
        except Exception:
            pass

    async def _write_commitment(self, event: AstrMessageEvent, text: str) -> None:
        try:
            bridge = self._get_memory_bridge()
            if bridge is None:
                return
            from .models import resolve_chat_provider as _resolve_commit

            provider, _pid = _resolve_commit(self.context, self.config, "commitment")
            if provider is None:
                return
            resp = await chat_text(provider, self.config, prompt=build_commitment_prompt(text), session_id="storyteller_commitment")
            content = str(getattr(resp, "completion_text", "") or "").strip()
            if not content:
                return
            memory_id = await write_memory(
                bridge, content=content, memory_type="promise", event=event, importance=0.6
            )
            if memory_id:
                logger.info("[Storyteller] 已写入约定/愿望: %s", content[:60])
        except Exception as exc:
            logger.warning("[Storyteller] 写入约定失败: %s", exc)

    async def _flush_profile(self) -> None:
        """从画像素材提炼并写入记忆（带已有画像去重）。"""
        if not self._profile_buffer:
            return
        if not self.config.bool("memory.profile_enabled", True):
            self._profile_buffer = []
            return
        items = self._profile_buffer[:]
        self._profile_buffer = []
        try:
            bridge = self._get_memory_bridge()
            if bridge is None:
                return
            provider, provider_id = resolve_chat_provider(self.context, self.config, "profile")
            if provider is None:
                return
            ctx = items[0].get("ctx") if items else {}
            existing = self._existing_profile_items(bridge, ctx)
            resp = await chat_text(provider, self.config, prompt=build_profile_prompt([it["text"] for it in items], existing), session_id="storyteller_profile")
            self._record_usage(resp, "profile", provider_id or "default")
            profiles = parse_profile_items(str(getattr(resp, "completion_text", "") or ""))
            for content in profiles:
                memory_id = await bridge.add_memory(
                    content=content,
                    memory_type="preference",
                    session_context=ctx,
                    importance=0.5,
                    source_plugin="astrbot_plugin_storyteller",
                )
                if memory_id:
                    logger.info("[Storyteller] 已写入用户画像: %s", content[:60])
        except Exception as exc:
            logger.warning("[Storyteller] 提炼画像失败: %s", exc)

    def _existing_profile_items(self, bridge: Any, ctx: dict[str, Any]) -> list[str]:
        """取已有画像（用于去重）。"""
        try:
            lister = getattr(bridge, "list_recent_memories", None)
            if not callable(lister):
                return []
            records = lister(session_context=ctx, limit=20, memory_type="preference")
            out: list[str] = []
            for r in records or []:
                if isinstance(r, dict):
                    content = str(r.get("content") or r.get("summary") or "").strip()
                    if content:
                        out.append(content[:80])
            return out
        except Exception:
            return []

    # ------------------------------------------------------------ 身份锚

    def _build_identity_anchor(self, event: AstrMessageEvent) -> str:
        """防认错锚注入内容（{身份} 占位符被取代的文本）。

        用户可在「防认错」页自定义（identity.custom_text）：配置了则用配置内容，
        其中可引用 {当前用户}/{场合} 占位符（注入时替换）；留空则自动生成防认错提示
        （当前对话对象、ID 唯一、换昵称不认错、自称别人不轻信、对陌生人保持距离等），
        并把最近一次自动生成内容缓存，供页面预览「{身份} 被取代后的内容」。
        """
        uid = str(getattr(event, "unified_msg_origin", "") or "")
        user = self._current_user_label(event)
        place = self._place_label(event)
        custom = str(self.config.get("identity.custom_text", "") or "").strip()
        if custom:
            from .intercept import replace_template

            return replace_template(custom, {"current_user": user, "place": place})
        try:
            anchor = build_identity_anchor(event, memory_name=self._memory_name(event), current_user=user, place=place)
        except Exception:
            anchor = ""
        if anchor:
            self._last_identity_anchor = anchor
        return anchor

    def _sender_id(self, event: AstrMessageEvent) -> str:
        sender = extract_sender(event)
        return sender.get("user_id") or ""

    def _memory_name(self, event: AstrMessageEvent) -> str:
        bridge = self._get_memory_bridge()
        if bridge is None:
            return ""
        try:
            getter = getattr(bridge, "get_user", None)
            if not callable(getter):
                return ""
            sender = extract_sender(event)
            user_id = sender.get("user_id") or ""
            session_id = sender.get("session_id") or ""
            platform = session_id.split(":", 1)[0] if ":" in session_id else ""
            if not user_id or not platform:
                return ""
            user = getter(f"{platform}:{user_id}")
            if isinstance(user, dict):
                return str(user.get("name") or "").strip()[:80]
        except Exception:
            pass
        return ""

    # ------------------------------------------------------------ 工具

    @filter.llm_tool(name="get_schedule")
    async def get_schedule_tool(self, event: AstrMessageEvent, **kwargs: Any) -> str:
        """查看「我」今天的日程、未来规划与延误事项。

        当对话提到时间安排、任务、计划、约了什么时候、某时间做什么时，优先调用此工具检索，
        再结合结果回复；不要凭空编造日程。

        Args:
            （无参数）
        """
        import json as _json

        sched = self.schedule_store.load()
        return _json.dumps(sched, ensure_ascii=False)

    @filter.llm_tool(name="set_schedule")
    async def set_schedule_tool(self, event: AstrMessageEvent, **kwargs: Any) -> str:
        """改写「我」某时段的日程安排。

        当对方要求「我」在某个时间做某事（例如三点半叫我起床）时调用：先检索日程，
        若该时段已有安排，原安排会自动转入「延误日程」缓存池并标注原因，之后有空再补。

        Args:
            time(string): 时间段起点，HH:MM 格式（如 "03:30"）。
            activity(string): 新的活动内容（如 "叫对方起床"）。
            note(string): 可选，改写原因（如 "对方让我三点半叫他"）。
        """
        start = str(kwargs.get("time") or kwargs.get("start") or "").strip()
        activity = str(kwargs.get("activity") or "").strip()
        note = str(kwargs.get("note") or "").strip()
        if not start or not activity:
            return "参数不完整：需要 time 和 activity"
        sched = self.schedule_store.replace(start=start, activity=activity, note=note)
        import json as _json

        return _json.dumps(sched, ensure_ascii=False)

    @filter.llm_tool(name="get_outfit")
    async def get_outfit_tool(self, event: AstrMessageEvent, **kwargs: Any) -> str:
        """查看「我」的当前穿搭与衣柜。

        当对话提到穿什么、穿搭、衣服、衣柜时调用。

        Args:
            （无参数）
        """
        import json as _json

        wardrobe = self.wardrobe_store.load()
        return _json.dumps(wardrobe, ensure_ascii=False)

    @filter.llm_tool(name="set_outfit")
    async def set_outfit_tool(self, event: AstrMessageEvent, **kwargs: Any) -> str:
        """修改「我」的当前穿搭（从衣柜里选）。

        当对方要求「我」换穿搭、穿某件衣服时调用。

        Args:
            items(string): 要穿的衣物，用顿号或逗号分隔（如 "白色连衣裙、帆布鞋"）。
            note(string): 可选，这样穿的理由。
        """
        raw = str(kwargs.get("items") or "").strip()
        note = str(kwargs.get("note") or "").strip()
        items = [x for x in raw.replace("，", ",").replace("、", ",").split(",") if x.strip()]
        if not items:
            return "参数不完整：需要 items"
        self.wardrobe_store.set_outfit(items, note)
        import json as _json

        return _json.dumps(self.wardrobe_store.load(), ensure_ascii=False)

    @filter.llm_tool(name="add_future_plan")
    async def add_future_plan_tool(self, event: AstrMessageEvent, **kwargs: Any) -> str:
        """把一件事记入「我」的未来规划（还没排进具体某天）。

        当对方提到以后想一起做的事、约定但没定时间时调用。

        Args:
            activity(string): 计划内容（如 "周末一起去看展"）。
            date(string): 可选，大致日期（YYYY-MM-DD）。
            note(string): 可选，备注。
        """
        activity = str(kwargs.get("activity") or "").strip()
        date = str(kwargs.get("date") or "").strip()
        note = str(kwargs.get("note") or "").strip()
        if not activity:
            return "参数不完整：需要 activity"
        self.schedule_store.add_future(activity=activity, date=date, note=note)
        import json as _json

        return _json.dumps(self.schedule_store.load().get("future", []), ensure_ascii=False)

    @staticmethod
    def _safe_call(event: Any, name: str) -> str:
        func = getattr(event, name, None)
        if not callable(func):
            return ""
        try:
            value = func()
            return str(value or "")[:80]
        except Exception:
            return ""

    # ------------------------------------------------------------ 生命周期

    async def initialize(self):
        self.proactive.start()
        self._mind_task = asyncio.ensure_future(self._mind_loop())
        # 启动预警（0.147）：模型链缺失提示——「接管改换」模式下 Bot 会降级放行主链
        try:
            fb = str(self.config.get("models.fallback_provider_id", "") or "").strip()
            tk = str(self.config.get("intercept.provider_id", "") or "").strip()
            if not fb and not tk:
                logger.warning(
                    "[Storyteller] 未配置任何模型（回退模型与接管模型均为空）："
                    "「接管改换」模式下接管请求将按「接管失败时」策略处理（默认降级放行主链）。"
                    "强烈建议到 WebUI「模型」页配置回退模型，确保拟人化回复生效。"
                )
        except Exception:
            pass

    async def terminate(self):
        await self.proactive.stop()
        if getattr(self, "_mind_task", None) is not None:
            self._mind_task.cancel()
        if self._memory_managed_active:
            bridge = self._get_memory_bridge()
            if bridge is not None:
                try:
                    setter = getattr(bridge, "set_injection_managed", None)
                    if callable(setter):
                        setter(False)
                except Exception:
                    pass
        logger.info("[Storyteller] %s 已停止", PLUGIN_DISPLAY)

    # ------------------------------------------------------------ 内心活动后台

    async def _mind_loop(self) -> None:
        """后台：按时间自动演化状态、生成日程、做梦、思考（不打扰主链）。

        0.171：启动后 ~60s 先跑首轮（补日程/状态；此前"先睡 30 分钟"导致开机后日程迟迟不生成）；
        日程缺失且上次尝试失败 → 5 分钟快重试（开机网络抖动场景），否则 30 分钟一轮。
        """
        from .mind import dream, think

        first_round = True
        while True:
            try:
                need_schedule = self.config.bool("schedule.enabled", True) and not self.schedule_store.load().get("entries")
                if first_round:
                    first_round = False
                    await asyncio.sleep(60)
                elif need_schedule and getattr(self, "_schedule_failed_at", 0):
                    await asyncio.sleep(300)  # 上次网络/模型失败：快重试
                else:
                    await asyncio.sleep(1800)  # 每 30 分钟一轮
                import random as _random

                hh = _hhmm()
                is_night = "23" <= hh < "24" or hh < "06"
                if self.config.bool("schedule.enabled", True) and not self.schedule_store.load().get("entries"):
                    _res = await self._generate_schedule()
                    self._schedule_failed_at = time.time() if not _res.get("ok") else 0
                if self.config.bool("presence.enabled", True) and self.config.bool("presence.auto_refresh", True):
                    await self._refresh_presence()
                # ── 深夜：一夜只一条长梦（素材=白天的事），23 点后补日记 ──
                if is_night and self.config.bool("mind.enabled", True):
                    if not self.mind_store.meta_get("last_dream_date") == time.strftime("%Y-%m-%d"):
                        day_context = self._dream_material()
                        d = await dream(self, day_context=day_context, long_dream=True)
                        if d:
                            self.mind_store.add_dream(d)
                            self.mind_store.meta_set("last_dream_date", time.strftime("%Y-%m-%d"))
                            self.mind_store.meta_set("dream_aftermath", self._dream_aftermath(d))
                            logger.info("[Storyteller] 已生成一夜长梦: %s 字", len(d))
                    # 写日记：优先按日程「写日记」段到点自动写（diary_time ±30 分钟窗口），
                    # 未在日程时段则 23 点后兑底
                    if not self.diary_store.has_today() and self._diary_due_now():
                        await self._write_diary()
                # ── 白天：事件驱动思考（30~90 分钟随机窗口 + 每日限次） ──
                elif self.config.bool("mind.enabled", True):
                    limit = max(1, min(24, self.config.int("mind.think_daily_limit", 7) or 7))
                    today = time.strftime("%Y-%m-%d")
                    if self.mind_store.meta_get("think_day") != today:
                        self.mind_store.meta_set("think_day", today)
                        self.mind_store.meta_set("think_count", 0)
                    count = int(self.mind_store.meta_get("think_count", 0) or 0)
                    if count < limit and self._recent_event_window():
                        last_ts = float(self.mind_store.meta_get("last_think_at", 0) or 0)
                        interval_min = max(5, (self.config.int("mind.think_interval_minutes", 60) or 60)) * 60
                        window = max(interval_min, _random.uniform(1800, 5400))  # 最小间隔 ∩ 30~90 分钟随机窗口
                        if time.time() - last_ts >= window:
                            topic = self._recent_event_text()
                            t = await think(self, topic=topic)
                            if t:
                                self.mind_store.add_thought(t)
                                self.mind_store.meta_set("last_think_at", time.time())
                                self.mind_store.meta_set("think_count", count + 1)
                                logger.info("[Storyteller] 已生成思考(%s/%s): %s", count + 1, limit, str(t)[:60])
                # 自主浏览：她闲时会自己上网刷新鲜事（受 search.browse_enabled 与间隔限制）
                if self.config.bool("mind.enabled", True):
                    try:
                        from .mind import browse

                        b = await browse(self)
                        if b.get("ok"):
                            logger.info("[Storyteller] 自主浏览见闻: %s", str(b.get("note") or "")[:80])
                    except Exception as exc:
                        logger.warning("[Storyteller] 自主浏览失败: %s", exc)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("[Storyteller] 内心活动异常: %s", exc)

    def _recent_event_window(self) -> bool:
        """最近 6 小时内是否发生过"事件"（对话/情绪/画像），否则不值得冒念头。"""
        try:
            if self._emotion_buffer or self._profile_buffer:
                return True
            if self.presence_store.load().get("history"):
                return True
            now = time.time()
            last_talk = getattr(self, "_last_talk_ts", 0)
            if last_talk and now - last_talk < 6 * 3600:
                return True
        except Exception:
            pass
        return False

    def _recent_event_text(self) -> str:
        """把最近发生的事拼成一段"由头"。"""
        parts: list[str] = []
        try:
            if self._emotion_buffer:
                parts.append("对方最近的情绪：" + "；".join(self._emotion_buffer[-3:]))
            items = self._profile_buffer[-4:] if self._profile_buffer else []
            texts = [str(it.get("text") or "")[:80] for it in items if isinstance(it, dict)]
            if texts:
                parts.append("最近聊到的/发生的：" + "；".join(texts))
            try:
                from .schedule import current_activity

                activity = current_activity(self.schedule_store.load(), _hhmm())
                if activity:
                    parts.append(f"此刻按日程在做：{activity}")
            except Exception:
                pass
        except Exception:
            pass
        return "；".join(parts)

    def _dream_material(self) -> str:
        """白天素材：今天的状态史/情绪/画像/见闻/约定愿望，揉进长梦。"""
        parts: list[str] = []
        try:
            presence = self.presence_store.load()
            if presence.get("history"):
                from .presence import _history_text

                hist = _history_text(presence.get("history"))
                if hist:
                    parts.append("今天的心情起伏：" + hist)
            if self._emotion_buffer:
                parts.append("对方今天的心情：" + "；".join(self._emotion_buffer[-5:]))
            items = self._profile_buffer[-12:] if self._profile_buffer else []
            texts = [str(it.get("text") or "")[:80] for it in items if isinstance(it, dict)]
            if texts:
                parts.append("今天发生的事/聊到的：" + "；".join(texts))
            mind = self.mind_store.all()
            if mind.get("sightings"):
                parts.append("今天刷到的：" + "；".join(str(s.get("text") or "")[:60] for s in mind["sightings"][:3]))
            mem = self._recent_memory_hint(limit=6)
            if mem:
                parts.append("心里记着的：" + mem)
        except Exception:
            pass
        return "\n".join(parts)

    def _dream_aftermath(self, dream_text: str) -> str:
        """从长梦内容推断"余波"（供状态演化/主动对话取材）。"""
        text = str(dream_text or "")
        if not text:
            return ""
        scary = ("鬼", "追", "杀", "血", "死", "摔", "坠", "哭", "喊", "救", "黑暗", "怪", "蠕", "刀", "逃", "噩梦", "惊吓")
        warm = ("笑", "抱", "暖", "甜", "开心", "花园", "阳光", "海", "一起", "逛街", "蛋糕", "花")
        if any(k in text for k in scary):
            return "nightmare"
        if any(k in text for k in warm):
            return "sweet"
        return "ordinary"

    def _diary_due_now(self) -> bool:
        """到「写日记」点了吗？按日程里 diary_time ±30 分钟窗口；日程未安排则该时段兑底 23 点后。"""
        try:
            hhmm = _hhmm()
            hh = hhmm[:2]
            # 22:30 之前不写
            if hh < "22":
                return False
            diary_time = str(self.config.get("schedule.diary_time", "23:30") or "23:30").strip()[:5]
            try:
                th, tm = diary_time.split(":")
                anchor = int(th) * 60 + int(tm)
            except Exception:
                anchor = 23 * 60 + 30
            try:
                ch, cm = hhmm.split(":")
                now_min = int(ch) * 60 + int(cm)
            except Exception:
                now_min = 0
            # ±30 分钟窗口内写
            if abs(now_min - anchor) <= 30:
                return True
            # 凌晨（00:00~01:00）且昨天安排了写日记、今天还没写 → 补写（睡得晚）
            if hh < "01":
                return True
        except Exception:
            pass
        return False

    def _diary_material(self) -> str:
        """日记素材：人格/性格/记忆/亲近的人 + 当天状态史/梦/思/见闻/对方情绪。

        与「一键生成日程」提示词同源的素材库，供写日记与预览面板共用。
        """
        parts: list[str] = []
        try:
            persona_injection = str(self.persona_store.injection_text() or "")
            voice = self.voice_store.load()
            persona_desc = str(voice.get("tone") or "")
            if persona_injection:
                parts.append("她是谁（人格与世界观念）：\n" + persona_injection[:800])
            if persona_desc:
                parts.append("她的性格/说话方式：" + persona_desc)
            mem = self._recent_memory_hint(limit=8)
            if mem:
                parts.append("最近记得的约定/愿望/重要事：" + mem)
            try:
                rels = self.relationship_store.list_all()
                if rels:
                    rel_text = "；".join(
                        f"{str(r.get('user_name') or r.get('user_id') or '')}（好感 {r.get('affection', '?')}）"
                        for r in rels[:6] if isinstance(r, dict)
                    )
                    if rel_text:
                        parts.append("她最近亲近的人：" + rel_text)
            except Exception:
                pass
            presence = self.presence_store.load()
            if presence.get("history"):
                from .presence import _history_text

                hist = _history_text(presence.get("history"))
                if hist:
                    parts.append("今天的状态变化：\n" + hist)
            mind = self.mind_store.all()
            if mind.get("dreams"):
                parts.append("做的梦：" + "；".join(str(d.get("text") or "") for d in mind["dreams"][:3]))
            if mind.get("thoughts"):
                parts.append("冒出的念头：" + "；".join(str(t.get("text") or "") for t in mind["thoughts"][:5]))
            if mind.get("sightings"):
                parts.append("看到的见闻：" + "；".join(str(s.get("text") or "") for s in mind["sightings"][:3]))
            if self._emotion_buffer:
                parts.append("对方的情绪：" + "；".join(self._emotion_buffer[-5:]))
        except Exception:
            pass
        return "\n".join(parts)

    async def _write_diary(self) -> None:
        """收集当天素材，整理成一篇今日日记。"""
        try:
            from .models import resolve_chat_provider

            provider, provider_id = resolve_chat_provider(self.context, self.config, "diary")
            if provider is None:
                return
            # 日记素材共用（人格/记忆/当天经历）
            day_context = self._diary_material()
            resp = await chat_text(
                provider, self.config, prompt=build_diary_prompt(day_context), session_id="storyteller_diary",
                _max_tokens=1600,  # 日记是"睡前随手写几行"：计划内预算 + 默认关闭思考 → 快速稳定
            )
            self._record_usage(resp, "diary", provider_id or "default")
            content = str(getattr(resp, "completion_text", "") or "").strip()
            if content:
                self.diary_store.add(time.strftime("%Y-%m-%d", time.localtime()), content)
                logger.info("[Storyteller] 已写今日日记: %s 字", len(content))
        except Exception as exc:
            logger.warning("[Storyteller] 写日记失败: %s", exc)

    async def _generate_schedule(self) -> dict:
        """结合记忆/人格/天气/衣柜生成今天完整日程 + 穿搭。

        返回 {"ok": bool, "entries": int, "outfit": bool, "error": str}，
        供一键生成路由如实反馈成败（后台节拍调用方可忽略返回值）。
        """
        result = {"ok": False, "entries": 0, "outfit": False, "error": ""}
        try:
            from .models import resolve_chat_provider
            from .presence import build_presence_anchor
            from .schedule import build_schedule_generate_prompt, parse_schedule

            provider, provider_id = resolve_chat_provider(self.context, self.config, "schedule")
            if provider is None:
                result["error"] = "日程模型未配置（请在日程页选择模型，或配置「留空回退模型」）"
                return result
            voice = self.voice_store.load()
            persona_desc = str(voice.get("tone") or "")
            persona_injection = str(self.persona_store.injection_text() or "")
            weather = str(self.config.get("presence.weather", "") or "").strip()
            presence = build_presence_anchor(self.presence_store.load())
            memories = self._recent_memory_hint(limit=6)
            closet = self.wardrobe_store.closet_items()
            sched = self.schedule_store.load()
            prompt = build_schedule_generate_prompt(
                persona_desc=persona_desc,
                persona_injection=persona_injection,
                memories=memories,
                weather=weather,
                presence=presence,
                closet=closet,
                future=sched.get("future"),
                backlog=sched.get("backlog"),
                diary_time=str(self.config.get("schedule.diary_time", "23:30") or "23:30").strip()[:5],
                diary_minutes=max(5, min(60, self.config.int("schedule.diary_minutes", 20) or 20)),
            )
            logger.info("[Storyteller] 开始生成日程（模型: %s）", provider_id or "default")
            resp = await chat_text(
                provider, self.config, prompt=prompt, session_id="storyteller_schedule_auto",
                _max_tokens=4000,  # 0.175 回退 0.174 实验性预算增大：直连默认「关闭思考」→ 模型在预算内直接输出，无需大预算
            )
            self._record_usage(resp, "schedule", provider_id or "default")
            raw_text = str(getattr(resp, "completion_text", "") or "")
            data = parse_schedule(raw_text)
            # 0.173：解析失败（模型输出被截断/畸形，凭运气）→ 立即重试一次再判失败
            if not isinstance(data, dict) and raw_text.strip():
                logger.warning("[Storyteller] 日程生成解析失败，立即重试一次…")
                resp2 = await chat_text(
                    provider, self.config, prompt=prompt, session_id="storyteller_schedule_auto",
                    _max_tokens=4000,
                )
                self._record_usage(resp2, "schedule", provider_id or "default")
                raw_text = str(getattr(resp2, "completion_text", "") or "")
                data = parse_schedule(raw_text)
            if not isinstance(data, dict):
                preview = raw_text[:120].replace("\n", " ")
                if not raw_text.strip():
                    result["error"] = "模型未输出内容（推理预算被占满，请稍后再试或换模型）"
                    logger.warning("[Storyteller] 日程生成空输出（模型未给出任何内容），前 120 字: %s", preview)
                else:
                    result["error"] = "生成结果无法解析为日程 JSON（已重试一次仍失败，请手动生成）"
                    logger.warning(
                        "[Storyteller] 日程生成解析失败（重试一次后仍失败，原文 %s 字），前 120 字: %s",
                        len(raw_text), preview,
                    )
                return result
            entries = data.get("entries")
            outfit = data.get("outfit")
            if isinstance(entries, list) and entries:
                self.schedule_store.save_entries(entries)
                result["entries"] = len(entries)
                logger.info("[Storyteller] 已生成今日日程: %s 段", len(entries))
            if isinstance(outfit, dict) and outfit.get("items"):
                self.wardrobe_store.set_outfit(outfit.get("items") or [], outfit.get("note") or "")
                result["outfit"] = True
                logger.info("[Storyteller] 已生成今日穿搭: %s", "、".join(outfit.get("items") or []))
            if isinstance(data.get("closet"), list) and data["closet"]:
                self.wardrobe_store.set_closet(data["closet"])
                logger.info("[Storyteller] 已更新衣柜: %s 件", len(data["closet"]))
            result["ok"] = bool(result["entries"] or result["outfit"])
            if not result["ok"]:
                result["error"] = "生成结果为空（模型未给出日程或穿搭）"
                logger.warning("[Storyteller] 日程生成结果为空，前 120 字: %s", raw_text[:120].replace("\n", " "))
            return result
        except Exception as exc:
            result["error"] = str(exc) or type(exc).__name__
            logger.warning("[Storyteller] 日程自动生成失败: %s", exc)
            return result

    async def _refresh_presence(self, *, manual: bool = False, event: AstrMessageEvent | None = None) -> None:
        """按「当下」演化状态：时间/时间底色/日程/天气/最近余波/最近对话/上次状态。

        长期记忆不是情绪驱动器；仅当 presence.memory_drydock 开启时才按当前会话取最近约定 top1
        作为可选的「心事素材」（标注联动记忆插件，不走 embedding）。
        """
        try:
            from .models import resolve_chat_provider
            from .presence import build_presence_generate_prompt, parse_presence
            from .schedule import current_activity

            provider, provider_id = resolve_chat_provider(self.context, self.config, "presence")
            if provider is None:
                return
            self._last_presence_beat = time.time()
            now = time.strftime("%Y-%m-%d %H:%M", time.localtime())
            schedule = self.schedule_store.load()
            activity = current_activity(schedule, _hhmm())
            weather = str(self.config.get("presence.weather", "") or "").strip()
            schedule_part = activity or ""
            time_bg = ""
            if self.config.bool("presence.time_bg_enabled", True):
                from .presence import _compose_time_bg

                time_bg = _compose_time_bg(
                    now, schedule if self.config.bool("schedule.enabled", True) else None
                )
            if weather:
                schedule_part = f"{schedule_part}；天气：{weather}".strip("；")
            previous = self.presence_store.load()
            echoes = self._presence_echoes_text(previous)
            memory_material = ""
            if event is not None and self.config.bool("presence.memory_drydock", False):
                memory_material = self._recent_promise_hint(event)
            context = self._recent_context_hint(limit=3)
            prompt = build_presence_generate_prompt(
                now=now, schedule=schedule_part, context=context,
                previous=previous, weather=weather, time_bg=time_bg,
                echoes=echoes, memory_material=memory_material,
            )
            resp = await chat_text(
                provider, self.config, prompt=prompt, session_id="storyteller_presence_auto",
                _max_tokens=800,  # 状态锚很短，预算保险丝给足即可（默认关闭思考 → 快速）
            )
            self._record_usage(resp, "presence", provider_id or "default")
            presence = parse_presence(str(getattr(resp, "completion_text", "") or ""))
            if isinstance(presence, dict):
                presence["source"] = "manual" if manual else "auto"
                presence["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                self.presence_store.save(presence)
                logger.info("[Storyteller] 已演化状态(%s): %s", presence["source"], presence.get("mood", ""))
        except Exception as exc:
            logger.warning("[Storyteller] 状态演化失败: %s", exc)

    def _presence_echoes_text(self, presence: dict[str, Any]) -> str:
        """取最近余波（echoes，≤3 条）作为演化输入的当下素材。"""
        echoes = presence.get("echoes") or []
        parts = []
        for it in echoes[:3]:
            if isinstance(it, dict):
                text = str(it.get("text") or "").strip()
                kind = str(it.get("kind") or "") or ""
                if text:
                    label = {"分享": "对方刚分享", "求助": "对方刚求助", "道谢": "对方刚道谢", "争执": "刚才有点争执"}.get(kind, "刚才")
                    parts.append(f"{label}：{text[:50]}")
        return "；".join(parts)

    def _recent_promise_hint(self, event: AstrMessageEvent) -> str:
        """（可选心事素材）按当前会话取最近约定 top1；需已联动记忆插件，不走 embedding。"""
        bridge = self._get_memory_bridge()
        if bridge is None:
            logger.info("[Storyteller] 状态「心事素材」已开启，但未装载记忆插件，本次跳过")
            return ""
        try:
            lister = getattr(bridge, "list_recent_memories", None)
            if not callable(lister):
                return ""
            recs = lister(session_context=self._session_ctx_dict(event), limit=1, memory_type="promise")
            for rec in recs or []:
                if isinstance(rec, dict):
                    content = str(rec.get("content") or rec.get("summary") or "").strip()
                else:
                    content = str(getattr(rec, "content", "") or getattr(rec, "summary", "") or "").strip()
                if content:
                    return content[:80]
        except Exception:
            pass
        return ""

    def _recent_memory_hint(self, limit: int = 4) -> str:
        """取最近记忆作为状态演化的输入（约定/愿望/回想）。"""
        bridge = self._get_memory_bridge()
        if bridge is None:
            return ""
        try:
            lister = getattr(bridge, "list_recent_memories", None)
            if not callable(lister):
                return ""
            records = lister(session_context={}, limit=limit)
            if not isinstance(records, list):
                return ""
            items = []
            for r in records[:limit]:
                if isinstance(r, dict):
                    content = str(r.get("content") or r.get("summary") or "").strip()
                else:
                    content = str(getattr(r, "content", "") or getattr(r, "summary", "") or "").strip()
                if content:
                    items.append(content[:80])
            return "；".join(items)
        except Exception:
            return ""

    def _recent_promise_hint(self, limit: int = 3) -> str:
        """只取记忆库里的「约定/承诺（promise）」类最近记忆。

        主动由头（记忆源/约定后续）专用：不混入偏好、身份等其它记忆——
        否则会出现把「鱼罐头偏好」之类的记忆错当成「说好/约好的事」
        的幻觉由头（模型会演绎出「昨天说好的，今天你那边怎么样了」）。
        """
        bridge = self._get_memory_bridge()
        if bridge is None:
            return ""
        try:
            lister = getattr(bridge, "list_recent_memories", None)
            if not callable(lister):
                return ""
            records = lister(session_context={}, limit=limit, memory_type="promise")
            if not isinstance(records, list):
                return ""
            items = []
            for r in records[:limit]:
                if isinstance(r, dict):
                    content = str(r.get("content") or r.get("summary") or "").strip()
                else:
                    content = str(getattr(r, "content", "") or getattr(r, "summary", "") or "").strip()
                if content:
                    items.append(content[:100])
            return "；".join(items)
        except Exception:
            return ""

    def _recent_context_hint(self, limit: int = 3) -> str:
        """取最近情绪余波 + 对话素材作为状态演化的上下文。"""
        parts: list[str] = []
        if self._emotion_buffer:
            parts.append("对方最近的情绪：" + "；".join(self._emotion_buffer[-3:]))
        items = self._profile_buffer[-limit:] if self._profile_buffer else []
        profile_text = "；".join(str(it.get("text") or "").strip()[:80] for it in items if isinstance(it, dict))
        if profile_text:
            parts.append("最近对话：" + profile_text)
        return "；".join(parts)

    def _record_usage(self, resp: Any, task: str, model: str, *, source: str = "companion") -> None:
        """记一笔 token 用量。

        提供方返回真实 usage 时优先用真实值；字段缺失（或全零）时按文本估算兜底
        （输入估算由 chat_text 挂在结果的 est_input_tokens 上，输出按回复文本估算）。
        """
        if self.token_store is None:
            return
        try:
            usage = getattr(resp, "usage", None)
            inp_real = out_real = None
            if usage is not None:
                try:
                    inp_real = int(getattr(usage, "input_other", 0) or 0) + int(getattr(usage, "input_cached", 0) or 0)
                    out_real = int(getattr(usage, "output", 0) or 0)
                except Exception:
                    inp_real = out_real = None
            from .token_usage import estimate_tokens

            inp = inp_real if (inp_real or 0) > 0 else max(0, int(getattr(resp, "est_input_tokens", 0) or 0))
            out_text = str(getattr(resp, "completion_text", "") or "")
            out_text += str(getattr(resp, "reasoning_content", "") or "")
            out = out_real if (out_real or 0) > 0 else estimate_tokens(out_text)
            if inp == 0 and out == 0:
                return
            self.token_store.record(source=source, task=task, model=model, input_tokens=inp, output_tokens=out)
        except Exception:
            pass

    # ------------------------------------------------------------ 主链（AstrBot）Token 记账

    def _note_main_chain_input(self, event: AstrMessageEvent, req: Any) -> None:
        """主链放行前（真实调用会发生）：把最终请求的输入估算挂到事件上，供 on_llm_response 配对。

        三种真实调用模式都调用：监视 / 放行 / 接管走主链。
        接管改换是插件自己直连生成（不走主链），不计入主链、由 _record_usage(companion) 记账。
        """
        try:
            parts: list[str] = []
            if req is not None:
                if str(getattr(req, "system_prompt", "") or "").strip():
                    parts.append(str(req.system_prompt))
                for ctx in getattr(req, "contexts", None) or []:
                    if isinstance(ctx, dict):
                        content = ctx.get("content")
                        if isinstance(content, list):
                            content = " ".join(
                                str(p.get("text", "")) for p in content if isinstance(p, dict) and p.get("text")
                            )
                        parts.append(str(content or ""))
                    else:
                        parts.append(str(getattr(ctx, "content", "") or ""))
                if str(getattr(req, "prompt", "") or "").strip():
                    parts.append(str(req.prompt))
            from .token_usage import estimate_tokens

            payload = {
                "inp": estimate_tokens(" ".join(parts)),
                "model": str(getattr(req, "model", "") or "") or "default",
            }
            try:
                setattr(event, "_storyteller_main_chain_usage", payload)
            except Exception:
                pass
        except Exception:
            pass

    def _record_astr_total(self, event: AstrMessageEvent, resp: Any) -> None:
        """AstrBot 主链全局记账（source=astr_total）：所有主链 LLM 响应的真实 usage。

        0.148 起：放行/监视/接管走主链由 _record_main_chain_usage 记「主链代记」（仅本插件介入会话），
        这里无条件记录全部主链调用（含拦截关闭/命令消息等本插件未介入的会话）——
        让「AstrBot 总消耗」卡反映真实全量；非 AI 生图等非主链调用天然不在其中。
        """
        if resp is None or self.token_store is None:
            return
        try:
            if str(getattr(resp, "role", "") or "") in ("err", "error"):
                return
            usage = getattr(resp, "usage", None)
            inp = out = 0
            model = "default"
            if usage is not None:
                try:
                    inp = int(getattr(usage, "input_other", 0) or 0) + int(getattr(usage, "input_cached", 0) or 0)
                    out = int(getattr(usage, "output", 0) or 0)
                    model = str(getattr(usage, "model", "") or "") or "default"
                except Exception:
                    inp = out = 0
            if inp == 0 and out == 0:
                # 无真实 usage 的可观测调用也估算占比（避免卡片长期为 0 误导）
                from .token_usage import estimate_tokens

                out_text = str(getattr(resp, "completion_text", "") or "")
                out_text += str(getattr(resp, "reasoning_content", "") or "")
                out = estimate_tokens(out_text)
            if inp == 0 and out == 0:
                return
            self.token_store.record(source="astr_total", task="main_chain", model=model, input_tokens=inp, output_tokens=out)
        except Exception:
            pass

    def _record_main_chain_usage(self, event: AstrMessageEvent, resp: Any) -> None:
        """主链真实响应（on_llm_response）记一笔：source=main。

        输入取真实 usage，缺失时用 on_llm_request 挂上的估算；输出取真实 usage，
        缺失时按回复文本（含思考内容）估算。出错响应（role=err）不记输出。
        """
        if resp is None or self.token_store is None:
            return
        try:
            if str(getattr(resp, "role", "") or "") in ("err", "error"):
                return
            pending = getattr(event, "_storyteller_main_chain_usage", None)
            inp = max(0, int((pending or {}).get("inp", 0) or 0)) if isinstance(pending, dict) else 0
            model = str((pending or {}).get("model") or "default") if isinstance(pending, dict) else "default"
            usage = getattr(resp, "usage", None)
            inp_real = out_real = None
            if usage is not None:
                try:
                    inp_real = int(getattr(usage, "input_other", 0) or 0) + int(getattr(usage, "input_cached", 0) or 0)
                    out_real = int(getattr(usage, "output", 0) or 0)
                except Exception:
                    inp_real = out_real = None
            from .token_usage import estimate_tokens

            if (inp_real or 0) > 0:
                inp = inp_real
            out_text = str(getattr(resp, "completion_text", "") or "")
            out_text += str(getattr(resp, "reasoning_content", "") or "")
            out = out_real if (out_real or 0) > 0 else estimate_tokens(out_text)
            if inp == 0 and out == 0:
                return
            self.token_store.record(source="main", task="main_chain", model=model, input_tokens=inp, output_tokens=out)
        except Exception:
            pass
