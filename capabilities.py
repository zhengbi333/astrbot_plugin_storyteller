"""能力注册表：把插件能力统一暴露给 LLM（主链工具 + 接管文本协议）。

设计要点（独立实现，不与外部插件雷同）：
- **单一真源**：每个能力只声明一次（名称/说明/参数/适用模式/限额/是否需要设定写权限），
  主链工具注册与接管模式的声明段都从这里生成，避免"两处各写一份、行为分叉"；
- **两种暴露方式**：
  1. 主链模式（放行 / 接管走主链）：由 AstrBot 注册为 LLM 工具，模型原生 function calling；
  2. 接管改换：直连链路不带 tools，改为把能力清单写进 system 声明段，
     模型输出 `[DO:能力名]{json}` 表达意愿，插件解析执行（0.196 确定的协议格式）；
- **结果统一结构**：{ok, status, message, next_hint}——`next_hint` 直接引导模型下一句怎么说
  （借鉴"失败可见/不谎称已做"的经验：只有真成功才允许说做到了）；
- **去重**：本轮已通过能力执行的动作会登记到 event 上，供各预检测判断"这个动作已经有人做了"，
  避免"模型调了搜索 + 正则又搜一次"这类双重执行。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

# 协议：模型输出 [DO:能力名]{json}；解析后一定从可见文本里剔除
DO_PATTERN = re.compile(r"\[DO:([a-zA-Z_][a-zA-Z0-9_]{1,40})\]\s*(\{[^{}]*\}|\[[^\[\]]*\])?")


@dataclass
class Capability:
    """一个能力的声明（描述 + 参数 + 约束）。"""

    name: str
    title: str
    description: str
    params: dict[str, str] = field(default_factory=dict)  # 参数名 -> 说明
    example: str = ""
    modes: tuple[str, ...] = ("主链", "接管")   # 适用链路
    needs_settings_write: bool = False          # 需要 general.model_edit_settings 开关
    daily_limit_key: str = ""                   # 每日限额配置键（空=不限）
    enums: dict[str, list[str]] = field(default_factory=dict)  # 枚举型参数的取值
    impl: Callable[..., Any] | None = None      # async (plugin, event, payload) -> dict

    def declaration(self) -> str:
        """生成给模型看的单行声明（接管模式声明段用）。"""
        params = "、".join(f"{k}（{v}）" for k, v in self.params.items()) if self.params else "无参数"
        line = f"- {self.name}：{self.description}｜参数：{params}"
        if self.example:
            line += f"｜示例：{self.example}"
        return line


# ---------------------------------------------------------------- 实现（async handler）

async def _impl_memory_write(plugin: Any, event: Any, payload: dict) -> dict[str, Any]:
    """写入长期记忆（事实/偏好/约定/待办）。"""
    content = str(payload.get("content") or "").strip()
    if not content:
        return {"ok": False, "status": "error", "message": "content 不能为空"}
    note_type = str(payload.get("type") or "").strip() or "fact"
    if note_type not in ("fact", "preference", "promise", "note", "todo"):
        note_type = "fact"
    bridge = plugin._get_memory_bridge()
    if bridge is None:
        return {
            "ok": False, "status": "unavailable",
            "message": "记忆插件未联动，无法写入",
            "next_hint": "如实告诉对方这次没能存下来，别说「记住了」。",
        }
    from .memory import build_session_context

    try:
        mid = await bridge.add_memory(
            content=content,
            memory_type="note" if note_type == "todo" else note_type,
            session_context=build_session_context(event),
            importance=0.7 if note_type in ("promise", "todo") else 0.6,
            source_plugin="astrbot_plugin_storyteller",
        )
    except Exception as exc:
        return {
            "ok": False, "status": "error", "message": f"写入失败：{exc}",
            "next_hint": "如实说明这次没记住，别谎称已保存。",
        }
    if not mid:
        return {"ok": False, "status": "error", "message": "写入未返回 id",
                "next_hint": "如实说明这次没记住，别谎称已保存。"}
    return {
        "ok": True, "status": "ok", "memory_id": mid, "content": content, "type": note_type,
        "next_hint": "可以自然确认一句「记住了」之类，但别把内容复述成背诵。",
    }


async def _impl_memory_recall(plugin: Any, event: Any, payload: dict) -> dict[str, Any]:
    """检索长期记忆（回忆）。"""
    query = str(payload.get("query") or "").strip() or "关于对方最近的事"
    bridge = plugin._get_memory_bridge()
    if bridge is None:
        return {"ok": False, "status": "unavailable", "message": "记忆插件未联动",
                "next_hint": "如实说想不起来，别编造回忆。"}
    top_k = payload.get("top_k")
    try:
        top_k = max(1, min(10, int(top_k))) if top_k is not None else 5
    except Exception:
        top_k = 5
    try:
        results = await bridge.search(query, session_context=plugin._session_ctx_dict(event), top_k=top_k)
    except Exception as exc:
        return {"ok": False, "status": "error", "message": f"检索失败：{exc}",
                "next_hint": "如实说一时想不起来。"}
    items = []
    for r in (results or [])[:top_k]:
        if isinstance(r, dict):
            text = str(r.get("content") or r.get("summary") or "").strip()
            if text:
                items.append(text[:120])
    if not items:
        return {"ok": True, "status": "empty", "message": "没有相关记忆",
                "next_hint": "如实说记不太清了；不要编造没发生过的事。"}
    return {"ok": True, "status": "ok", "items": items,
            "next_hint": "用你自己的话自然提起（别罗列、别像查数据库）。"}


async def _impl_web_lookup(plugin: Any, event: Any, payload: dict) -> dict[str, Any]:
    """联网搜索并拿到可依据的要点。"""
    query = str(payload.get("query") or "").strip()
    if not query:
        return {"ok": False, "status": "error", "message": "query 不能为空"}
    if not plugin.config.bool("search.enabled", True):
        return {"ok": False, "status": "disabled", "message": "搜索未开启",
                "next_hint": "如实说现在查不了；别凭印象编数据。"}
    try:
        from .mind import search_and_think

        result = await search_and_think(plugin, query, count=5)
    except Exception as exc:
        return {"ok": False, "status": "error", "message": f"搜索失败：{exc}",
                "next_hint": "如实说没查到，别编造数据。"}
    note = str(result.get("note") or "").strip()
    rows = []
    for i, r in enumerate((result.get("results") or [])[:3], 1):
        if isinstance(r, dict):
            title = str(r.get("title") or "").strip()
            snippet = str(r.get("snippet") or "").strip()[:120]
            if title or snippet:
                rows.append(f"[{i}] {title}：{snippet}" if title else f"[{i}] {snippet}")
    if not note and not rows:
        return {"ok": True, "status": "empty", "message": "没有搜到内容",
                "next_hint": "如实说没查到。"}
    detail = "\n".join(([note] if note else []) + rows)
    try:
        session_id = str(getattr(event, "unified_msg_origin", "") or "")
        if session_id and detail:
            import time as _t

            plugin._search_result_cache[session_id] = (detail[:400], query, _t.time())
    except Exception:
        pass
    return {"ok": True, "status": "ok", "query": query, "detail": detail[:600],
            "next_hint": "用一句自然的话说出要点；没把握就说不确定，别编。"}


async def _impl_emoji_send(plugin: Any, event: Any, payload: dict) -> dict[str, Any]:
    """发一张表情包（按分类；不给分类则选第一个有图的）。"""
    store = getattr(plugin, "emoji_store", None)
    if store is None:
        return {"ok": False, "status": "unavailable", "message": "表情包模块未初始化"}
    user = ""
    try:
        from .persona import extract_sender

        user = extract_sender(event).get("user_id") or ""
    except Exception:
        user = ""
    try:
        if store.is_opt_out(user):
            return {"ok": False, "status": "skipped",
                    "message": "对方说过不想看表情包",
                    "next_hint": "尊重对方边界，只用文字自然回复。"}
    except Exception:
        pass
    try:
        cats = [c for c in store.categories() if store._files(str(c.get("id") or ""))]
    except Exception:
        cats = []
    if not cats:
        return {"ok": False, "status": "empty", "message": "图库里还没有图片",
                "next_hint": "只用文字回复（别说要发表情包）。"}
    want = str(payload.get("category") or "").strip()
    picked = None
    for c in cats:
        if want and (want == str(c.get("title") or "") or want in str(c.get("title") or "")):
            picked = c
            break
    if picked is None:
        picked = cats[0]
    title = str(picked.get("title") or "")
    return {"ok": True, "status": "ok", "category": title, "mark": f"[EMOJI:{title}]",
            "next_hint": "文字照常自然说，表情包会随消息一起发出去。"}


async def _impl_photo_take(plugin: Any, event: Any, payload: dict) -> dict[str, Any]:
    """画/拍一张图并直接发给对方（模型主动）。"""
    desc = str(payload.get("prompt") or "").strip()
    if not desc:
        return {"ok": False, "status": "error", "message": "prompt 不能为空"}
    if bool(payload.get("selfie")):
        desc = f"{desc}（角色本人的自拍/出镜）"
    try:
        ok, why = await plugin.image_gen.can_generate()
    except Exception as exc:
        return {"ok": False, "status": "error", "message": f"生图不可用：{exc}"}
    if not ok:
        return {
            "ok": False, "status": "unavailable", "message": why,
            "next_hint": "如实说现在没法拍/画，别声称已经发图。",
        }
    try:
        prompt = plugin._compose_image_prompt(desc)
        path, note = await plugin.image_gen.generate(prompt, kind="text2img")
    except Exception as exc:
        return {"ok": False, "status": "error", "message": f"生成失败：{exc}",
                "next_hint": "如实说没画出来。"}
    if not path:
        return {"ok": False, "status": "error", "message": note or "生成失败",
                "next_hint": "如实说没画出来。"}
    import asyncio as _aio

    session_id = str(getattr(event, "unified_msg_origin", "") or "")
    caption = str(plugin.config.get("image.caption", "") or "").strip()
    try:
        from astrbot.api.event import MessageChain

        sender = getattr(plugin.context, "send_message", None)
        if callable(sender) and session_id:
            chain = MessageChain()
            chain.file_image(path)
            if caption:
                chain.message(caption)
            await sender(session_id, chain)
    except Exception as exc:
        return {"ok": False, "status": "error", "message": f"发送失败：{exc}",
                "next_hint": "如实说图没发出去。"}
    try:
        plugin._note_bot_reply(event, f"[图片] {caption}（模型主动：{desc[:60]}）")
    except Exception:
        pass
    await _aio.sleep(0)
    return {
        "ok": True, "status": "ok", "sent": True, "path": path, "caption": caption,
        "next_hint": "图已经发出去了：接下来只用一两句自然的话接住，不要复述画面、别说「我发给你」。",
    }


async def _impl_schedule_edit(plugin: Any, event: Any, payload: dict) -> dict[str, Any]:
    """改当天日程某时段，或记一条未来规划。"""
    action = str(payload.get("action") or "replace").strip().lower()
    activity = str(payload.get("activity") or "").strip()
    if action in ("future", "plan") or payload.get("date"):
        if not activity:
            return {"ok": False, "status": "error", "message": "activity 不能为空"}
        try:
            plugin.schedule_store.add_future(
                activity=activity,
                date=str(payload.get("date") or "").strip(),
                note=str(payload.get("note") or "").strip(),
            )
        except Exception as exc:
            return {"ok": False, "status": "error", "message": f"记未来规划失败：{exc}"}
        return {"ok": True, "status": "ok", "activity": activity, "kind": "future",
                "next_hint": "记下了，自然应一声就好（别把日程念一遍）。"}
    start = str(payload.get("start") or "").strip()
    if not start or not activity:
        return {"ok": False, "status": "error", "message": "需要 start（如 14:00）与 activity"}
    try:
        result = plugin.schedule_store.replace(
            start=start, activity=activity,
            note=str(payload.get("note") or "").strip(), move_original=True,
        )
    except Exception as exc:
        return {"ok": False, "status": "error", "message": f"改日程失败：{exc}"}
    return {"ok": True, "status": "ok", "start": start, "activity": activity,
            "moved_original": bool((result or {}).get("moved")) if isinstance(result, dict) else None,
            "next_hint": "改好了：自然说一句就行，别把整张日程表念出来。"}


async def _impl_outfit_change(plugin: Any, event: Any, payload: dict) -> dict[str, Any]:
    """换当前穿搭，或往衣柜里添一件。"""
    add_item = str(payload.get("add_item") or "").strip()
    if add_item:
        try:
            plugin.wardrobe_store.add_item(add_item)
        except Exception as exc:
            return {"ok": False, "status": "error", "message": f"添衣柜失败：{exc}"}
        return {"ok": True, "status": "ok", "added": add_item,
                "next_hint": "可以自然提一句收进衣柜了。"}
    items = payload.get("items")
    if isinstance(items, str):
        items = [x.strip() for x in items.replace("、", ",").split(",") if x.strip()]
    if not isinstance(items, list) or not items:
        return {"ok": False, "status": "error", "message": "items（衣物名列表）不能为空"}
    names = [str(x).strip() for x in items if str(x).strip()][:8]
    try:
        plugin.wardrobe_store.set_outfit(names, note=str(payload.get("note") or "").strip())
    except Exception as exc:
        return {"ok": False, "status": "error", "message": f"换穿搭失败：{exc}"}
    return {"ok": True, "status": "ok", "items": names,
            "next_hint": "换好了：自然带一句（比如照镜子式的反应），别逐件念。"}


async def _impl_proactive_schedule(plugin: Any, event: Any, payload: dict) -> dict[str, Any]:
    """记下一件「我答应过要回访/以后要一起做」的事，交给既有由头链路去兑现。"""
    what = str(payload.get("what") or "").strip()
    if not what:
        return {"ok": False, "status": "error", "message": "what 不能为空"}
    when = str(payload.get("when") or "").strip()
    bridge = plugin._get_memory_bridge()
    if bridge is None:
        return {"ok": False, "status": "unavailable", "message": "记忆插件未联动",
                "next_hint": "别在回复里给承诺（记不下就别说会做）。"}
    from .memory import build_session_context

    content = f"我答应对方：{what}" + (f"（大约 {when}）" if when else "")
    try:
        mid = await bridge.add_memory(
            content=content, memory_type="promise",
            session_context=build_session_context(event), importance=0.75,
            source_plugin="astrbot_plugin_storyteller",
        )
    except Exception as exc:
        return {"ok": False, "status": "error", "message": f"写入失败：{exc}",
                "next_hint": "没能记下，别在回复里承诺。"}
    if not mid:
        return {"ok": False, "status": "error", "message": "写入未返回 id",
                "next_hint": "没能记下，别在回复里承诺。"}
    if when:
        try:
            plugin.schedule_store.add_future(activity=f"回访：{what}", date=when, note="答应过对方的事")
        except Exception:
            pass
    return {"ok": True, "status": "ok", "content": content,
            "next_hint": "已经替你记下：回复里可以说「我会记着」，但别把时间说得太满。"}


async def _impl_mood_note(plugin: Any, event: Any, payload: dict) -> dict[str, Any]:
    """让情绪随对话自然起伏（模型自述式微调，幅度受上限约束）。"""
    direction = str(payload.get("direction") or "up").strip().lower()
    reason = str(payload.get("reason") or "").strip()[:40]
    up = direction in ("up", "good", "positive", "好", "上")
    try:
        from .presence import clamp, stain
    except Exception as exc:
        return {"ok": False, "status": "error", "message": f"状态模块不可用：{exc}"}
    try:
        store = plugin.presence_store
        presence = store.load(with_decay=False)
        delta = 0.05 if up else -0.05
        presence["tone"] = clamp(float(presence.get("tone", 0.0)) + delta, -1.0, 1.0)
        presence["tempo"] = clamp(float(presence.get("tempo", 0.0)) + delta * 0.6, -1.0, 1.0)
        presence = stain(presence, "分享" if up else "低落", text=reason or ("聊得开心" if up else "有点闷"))
        import time as _t

        presence["updated_at"] = _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime())
        store.save(presence)
    except Exception as exc:
        return {"ok": False, "status": "error", "message": f"状态更新失败：{exc}"}
    return {"ok": True, "status": "ok", "direction": "up" if up else "down",
            "next_hint": "心情已经变了：可以自然带出一点情绪，但别解释机制。"}


async def _impl_share_inner(plugin: Any, event: Any, payload: dict) -> dict[str, Any]:
    """分享自己的梦 / 见闻 / 日记（同一条有冷却，避免反复念叨）。"""
    import time as _t

    kind = str(payload.get("kind") or "sighting").strip().lower()
    if kind in ("dream", "梦"):
        kind = "dream"
    elif kind in ("diary", "日记"):
        kind = "diary"
    else:
        kind = "sighting"
    text = ""
    try:
        if kind == "diary":
            entries = plugin.diary_store.entries() or []
            if entries:
                last = entries[-1]
                text = str(last.get("content") or last.get("text") or "").strip() if isinstance(last, dict) else str(last)
        else:
            key = "dreams" if kind == "dream" else "sightings"
            items = (plugin.mind_store.all() or {}).get(key) or []
            if items:
                first = items[0]
                text = str(first.get("text") or "") if isinstance(first, dict) else str(first)
    except Exception as exc:
        return {"ok": False, "status": "error", "message": f"读取失败：{exc}"}
    if not text:
        label = {"dream": "最近没做梦", "diary": "最近没写日记", "sighting": "最近没刷到什么"}[kind]
        return {"ok": True, "status": "empty", "message": label,
                "next_hint": f"如实说{label}（别编一个梦/见闻出来）。"}
    # 冷却：同一条 6 小时内不重复分享
    try:
        key = f"{kind}:{hash(text) & 0xFFFFFF}"
        last_at = float(plugin._cap_shared.get(key, 0) or 0)
        if _t.time() - last_at < 6 * 3600:
            return {"ok": False, "status": "cooling",
                    "message": "这条刚分享过",
                    "next_hint": "别再提同一件事了，正常聊别的。"}
        plugin._cap_shared[key] = _t.time()
    except Exception:
        pass
    return {"ok": True, "status": "ok", "kind": kind, "excerpt": text[:300],
            "next_hint": "用你自己的话随口提起（一两句，别整段念），像人忽然想到什么。"}


async def _impl_history_lookup(plugin: Any, event: Any, payload: dict) -> dict[str, Any]:
    """翻自己和对方最近的聊天记录（看历史）。"""
    try:
        limit = payload.get("limit")
        limit = max(1, min(30, int(limit))) if limit is not None else 10
    except Exception:
        limit = 10
    session_id = str(getattr(event, "unified_msg_origin", "") or "")
    try:
        text = plugin._recent_timeline_text(session_id, limit=limit)
    except Exception as exc:
        return {"ok": False, "status": "error", "message": f"读取失败：{exc}"}
    if not text:
        return {"ok": True, "status": "empty", "message": "没有更早的记录",
                "next_hint": "如实说记不太清之前聊过什么。"}
    return {"ok": True, "status": "ok", "timeline": text[:800],
            "next_hint": "像人回忆那样自然提起（别整段复述记录）。"}


# ---------------------------------------------------------------- 注册表

CAPABILITIES: dict[str, Capability] = {}


def _register(cap: Capability) -> None:
    CAPABILITIES[cap.name] = cap


_register(Capability(
    name="memory_write",
    title="记住一件事",
    description="把对方要你长期记住的内容写进长期记忆（事实/偏好/约定/待办）",
    params={"content": "要记住的内容（第三人称、精简一句）", "type": "fact|preference|promise|todo"},
    example='[DO:memory_write]{"content":"对方明天上午要去医院复查","type":"fact"}',
    enums={"type": ["fact", "preference", "promise", "todo"]},
    daily_limit_key="capabilities.memory_write_daily",
    impl=_impl_memory_write,
))

_register(Capability(
    name="memory_recall",
    title="回忆往事",
    description="检索你和对方过去的长期记忆（对方问「还记得…吗」或你想确认旧事时）",
    params={"query": "要回忆的关键词或问题", "top_k": "可选，默认 5"},
    example='[DO:memory_recall]{"query":"对方的口味偏好"}',
    daily_limit_key="capabilities.memory_recall_daily",
    impl=_impl_memory_recall,
))

_register(Capability(
    name="web_lookup",
    title="上网查一下",
    description="联网搜索当前信息（价格/新闻/事实核对），返回可依据的要点",
    params={"query": "搜索词"},
    example='[DO:web_lookup]{"query":"RTX 5090 显卡价格"}',
    daily_limit_key="capabilities.web_lookup_daily",
    impl=_impl_web_lookup,
))

_register(Capability(
    name="emoji_send",
    title="发一张表情包",
    description="从图库挑一张表情包随回复发出（想表达情绪时用）",
    params={"category": "可选，分类标题；不给则用第一个有图的分类"},
    example='[DO:emoji_send]{"category":"表达轻微吐槽"}',
    daily_limit_key="capabilities.emoji_send_daily",
    impl=_impl_emoji_send,
))

_register(Capability(
    name="photo_take",
    title="画/拍一张图发过去",
    description="画一张图（或角色自拍）并直接发给对方——想分享眼前画面、或对方想看时用",
    params={"prompt": "画面描述（谁/在哪/在做什么）", "selfie": "可选 true=角色本人出镜"},
    example='[DO:photo_take]{"prompt":"窗台上晒太阳的白猫，水彩风"}',
    daily_limit_key="image.max_daily",
    impl=_impl_photo_take,
))

_register(Capability(
    name="schedule_edit",
    title="改日程 / 记未来规划",
    description="改当天某个时段的安排，或把一件以后要做的事记进未来规划",
    params={"action": "replace（改当天某时段）| future（未来规划）", "start": "replace 用，如 14:00",
            "activity": "做什么", "date": "future 可选，如 周六/10-05", "note": "可选备注"},
    example='[DO:schedule_edit]{"action":"replace","start":"20:00","activity":"和对方一起看动画"}',
    enums={"action": ["replace", "future"]},
    daily_limit_key="capabilities.schedule_edit_daily",
    impl=_impl_schedule_edit,
))

_register(Capability(
    name="outfit_change",
    title="换穿搭 / 添衣服",
    description="换一身当前穿搭（从衣柜里选），或往衣柜里添一件新衣服",
    params={"items": "衣物名列表（可传数组或逗号分隔）", "add_item": "可选，往衣柜添一件"},
    example='[DO:outfit_change]{"items":["深灰毛衣","黑色牛仔裤"]}',
    daily_limit_key="capabilities.outfit_change_daily",
    impl=_impl_outfit_change,
))

_register(Capability(
    name="proactive_schedule",
    title="记下答应对方的事",
    description="答应对方「晚点找你/以后一起做某事」时记下来，之后由主动对话链路自然兑现",
    params={"what": "答应的事", "when": "可选，大约什么时候（如「今晚」「周末」）"},
    example='[DO:proactive_schedule]{"what":"晚点把查到的资料整理给对方","when":"今晚"}',
    daily_limit_key="capabilities.proactive_schedule_daily",
    impl=_impl_proactive_schedule,
))

_register(Capability(
    name="mood_note",
    title="情绪随对话起伏",
    description="这轮对话让你心情变好/变差时，让自己的情绪状态自然变化（幅度很小）",
    params={"direction": "up=变好 | down=变差", "reason": "可选，一句原因"},
    example='[DO:mood_note]{"direction":"up","reason":"被夸了"}',
    enums={"direction": ["up", "down"]},
    daily_limit_key="capabilities.mood_note_daily",
    impl=_impl_mood_note,
))

_register(Capability(
    name="share_inner",
    title="分享梦 / 见闻 / 日记",
    description="想起自己昨晚的梦、刚刷到的见闻或最近写的日记，想跟对方说一句时用",
    params={"kind": "dream=梦 | sighting=见闻 | diary=日记"},
    example='[DO:share_inner]{"kind":"dream"}',
    enums={"kind": ["dream", "sighting", "diary"]},
    daily_limit_key="capabilities.share_inner_daily",
    impl=_impl_share_inner,
))

_register(Capability(
    name="history_lookup",
    title="翻聊天记录",
    description="想确认「之前聊过什么」时翻最近的对话记录（不是长期记忆，是最近的原话）",
    params={"limit": "可选，默认 10 条"},
    example='[DO:history_lookup]{"limit":10}',
    daily_limit_key="capabilities.history_lookup_daily",
    impl=_impl_history_lookup,
))


# ---------------------------------------------------------------- 协议解析与分发

def available_capabilities(plugin: Any, mode: str) -> list[Capability]:
    """按链路与开关筛选出可用能力（未实现 handler 的不列出）。"""
    out: list[Capability] = []
    for cap in CAPABILITIES.values():
        if cap.impl is None:
            continue
        if mode not in cap.modes:
            continue
        if cap.needs_settings_write and not plugin.config.bool("general.model_edit_settings", False):
            continue
        out.append(cap)
    return out


def _param_schema(name: str, desc: str, enum: list[str] | None = None) -> dict:
    """按参数名/说明推断 OpenAI 兼容的参数 schema（宽松优先，够模型用即可）。"""
    base: dict = {"description": desc}
    if enum:
        base["type"] = "string"
        base["enum"] = list(enum)
        return base
    if name in ("items",):
        return {"type": "array", "items": {"type": "string"}, "description": desc}
    if name in ("selfie",):
        return {"type": "boolean", "description": desc}
    if name in ("top_k", "limit"):
        return {"type": "integer", "description": desc}
    return {"type": "string", "description": desc}


def build_tool_schemas(plugin: Any, mode: str, exclude: set[str] | None = None) -> list[dict]:
    """把能力清单转成 OpenAI 兼容的 tools schema（接管链路原生 function calling 用）。

    工具名统一 `story_<能力名>`，与主链模式注册的 `@filter.llm_tool` 同名，
    模型在两条链路看到的能力名一致；执行时用 `cap_name_from_tool` 映射回能力。
    `exclude`：本轮已由正则兜底做完的同类能力（不再给模型 → 消除双重执行）。
    """
    schemas: list[dict] = []
    skip = {str(x) for x in (exclude or set())}
    for cap in available_capabilities(plugin, mode):
        if cap.name in skip:
            continue  # 本轮正则兜底已做过同类动作 → 不再给模型，避免双重执行
        props: dict[str, dict] = {}
        required: list[str] = []
        for pname, pdesc in cap.params.items():
            props[pname] = _param_schema(pname, pdesc, (cap.enums or {}).get(pname))
            if "可选" not in str(pdesc):
                required.append(pname)
        schemas.append({
            "type": "function",
            "function": {
                "name": f"story_{cap.name}",
                "description": f"{cap.title}：{cap.description}" + (f"（示例：{cap.example}）" if cap.example else ""),
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        })
    return schemas


def cap_name_from_tool(tool_name: str) -> str:
    """工具名 → 能力名（去掉 story_ 前缀）。"""
    name = str(tool_name or "").strip()
    return name[6:] if name.startswith("story_") else name


def build_declaration(plugin: Any, mode: str) -> str:
    """生成接管模式的「能力声明段」（模型据此知道能做什么、怎么表达意愿）。"""
    caps = available_capabilities(plugin, mode)
    if not caps:
        return ""
    lines = [
        "【你可以主动做的事】（想做的时候，在回复里按格式写出下面这种标记，"
        "系统会替你去执行、然后把结果给你；不要假装已经做了）：",
    ]
    for cap in caps:
        lines.append(cap.declaration())
    lines.append(
        "格式：[DO:能力名]{\"参数\":\"值\"}——标记本身不会发给对方，你可以在它前后正常说话。"
        "不需要做的事就不要写标记；一次最多两个。"
    )
    return "\n".join(lines)


def parse_marks(text: str) -> list[tuple[str, dict]]:
    """从回复文本里解析 [DO:能力]{json}（容错：JSON 坏了就按空参数处理）。"""
    out: list[tuple[str, dict]] = []
    for m in DO_PATTERN.finditer(str(text or "")):
        name = m.group(1)
        raw = (m.group(2) or "").strip()
        payload: dict = {}
        if raw.startswith("{"):
            try:
                value = json.loads(raw)
                if isinstance(value, dict):
                    payload = value
            except Exception:
                payload = {}
        out.append((name, payload))
    return out


def strip_marks(text: str) -> str:
    """剔除 [DO:...] 标记（含其 JSON），保证不发给用户。"""
    cleaned = DO_PATTERN.sub("", str(text or ""))
    return re.sub(r"\s{2,}", " ", cleaned).strip()


async def dispatch(plugin: Any, event: Any, name: str, payload: dict) -> dict[str, Any]:
    """执行一个能力：开关/限额/去重登记一起处理。"""
    cap = CAPABILITIES.get(name)
    if cap is None or cap.impl is None:
        return {"ok": False, "status": "unknown", "message": f"没有这个能力：{name}"}
    if cap.needs_settings_write and not plugin.config.bool("general.model_edit_settings", False):
        return {"ok": False, "status": "forbidden", "message": "设定修改未开启（总览页开关）"}
    # 每日限额
    if cap.daily_limit_key:
        try:
            limit = max(0, int(plugin.config.int(cap.daily_limit_key, 0) or 0))
        except Exception:
            limit = 0
        if limit > 0:
            import time as _t

            day = _t.strftime("%Y-%m-%d", _t.localtime())
            used = plugin._cap_usage.get(f"{name}:{day}", 0)
            if used >= limit:
                return {"ok": False, "status": "limited",
                        "message": f"今天的「{cap.title}」次数用完了",
                        "next_hint": "如实说今天先不查/不弄了，别硬编。"}
    try:
        result = await cap.impl(plugin, event, payload or {})
    except Exception as exc:
        result = {"ok": False, "status": "error", "message": f"执行异常：{exc}"}
    if not isinstance(result, dict):
        result = {"ok": False, "status": "error", "message": "返回格式异常"}
    # 记额 + 去重标记
    if result.get("ok"):
        if cap.daily_limit_key:
            import time as _t

            day = _t.strftime("%Y-%m-%d", _t.localtime())
            key = f"{name}:{day}"
            plugin._cap_usage[key] = int(plugin._cap_usage.get(key, 0)) + 1
        try:
            done = getattr(event, "_storyteller_caps_done", None)
            if not isinstance(done, set):
                done = set()
                setattr(event, "_storyteller_caps_done", done)
            done.add(name)
        except Exception:
            pass
    result.setdefault("capability", name)
    return result


def caps_done(event: Any) -> set[str]:
    """本轮已经通过能力做完的动作集合（供预检测去重）。"""
    done = getattr(event, "_storyteller_caps_done", None)
    return done if isinstance(done, set) else set()


def mark_cap_done(event: Any, name: str) -> None:
    """登记「本轮这个动作已经做过了」（正则兜底做完后调用，用于抑制同类工具/预检测）。"""
    try:
        done = getattr(event, "_storyteller_caps_done", None)
        if not isinstance(done, set):
            done = set()
            setattr(event, "_storyteller_caps_done", done)
        done.add(str(name))
    except Exception:
        pass


def format_results(results: list[dict]) -> str:
    """把能力执行结果整理成给模型的追加提示（含 next_hint 的下一句引导）。"""
    if not results:
        return ""
    lines = ["【你刚才请求的事情，系统执行结果】"]
    for r in results:
        cap = str(r.get("capability") or "")
        if r.get("ok"):
            detail = str(r.get("detail") or r.get("message") or "")
            if r.get("items"):
                detail = "；".join(str(x) for x in r["items"][:5])
            if r.get("category"):
                detail = f"已选表情包分类：{r['category']}"
            if r.get("content"):
                detail = f"已记住：{r['content']}"
            lines.append(f"- {cap}：成功。{detail}")
        else:
            lines.append(f"- {cap}：未成功（{r.get('message') or r.get('status')}）。")
        hint = str(r.get("next_hint") or "").strip()
        if hint:
            lines.append(f"  提示：{hint}")
    lines.append("请据此自然回应对方向，不要提到标记或系统。")
    return "\n".join(lines)
