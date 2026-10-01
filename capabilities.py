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
