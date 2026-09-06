"""发送缓冲与「被抢话」裁决：Bot 回复像人一样"说完—被抢话—重新组织"。

设计要点（独立实现，不与示例插件雷同）：
- 只有「接管改换」链路的回复进缓冲（我们直连生成、我们发送；放行/走主链的回复由
  AstrBot 管线发送，无法缓存——页面与文档中说明）；
- 回复按自然句段拆成独立缓存条目，后台逐条发送（间隔按字数节奏，像打字停顿）；
- 用户在被发送期间抢话 → 调裁决模型（独立配置 send.interrupt_judge_provider_id，留空
  回退「判定模型」链）：A = 提速发完剩余并正常回新消息；B = 丢弃剩余，把「想说没
  说完的话」作为上下文注入本轮重新生成（像人被打断后重新组织语言）；
- 插件重载时未发送完的缓存丢弃（像话说一半被打断），不落盘。
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import threading
import time
from typing import Any

from .log import get_logger

logger = get_logger("发送缓冲")

_SENTENCE_SPLIT = re.compile(r"([。！？!?\n]+)")


def _now_ts() -> float:
    return time.time()


def _today_str() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def chunk_text(text: str, *, max_len: int = 46) -> list[str]:
    """把回复拆成自然句段（每条独立缓存）。

    - 按 。？！!?\n 断句，**每句独立一条**（像人一句一停）；
    - 单句超长（>max_len）按逗号/空格夹断；超短尾句（<6 字）并入前一条，避免仅发"嗯"。
    """
    text = (text or "").strip()
    if not text:
        return []
    raw_parts = [p for p in _SENTENCE_SPLIT.split(text) if p.strip()]
    merged: list[str] = []
    i = 0
    while i < len(raw_parts):
        seg = raw_parts[i]
        if i + 1 < len(raw_parts) and re.fullmatch(r"[。？!?\n]+", raw_parts[i + 1]):
            seg += raw_parts[i + 1]
            i += 1
        merged.append(seg.strip())
        i += 1
    pieces: list[str] = []
    for seg in merged:
        if len(seg) <= max_len:
            pieces.append(seg)
        else:
            pieces.extend(_hard_split(seg, max_len))
    # 超短尾句并入前一条（说话时不会只冒个语气词就停）
    if len(pieces) >= 2 and len(pieces[-1]) < 6:
        pieces[-2] = pieces[-2] + pieces[-1]
        pieces.pop()
    return [p for p in pieces if p]


def _hard_split(seg: str, max_len: int) -> list[str]:
    sub = re.findall(r"[^,，。；;！？!?\n]{1,%d}" % max_len, seg)
    return [p for p in sub if p.strip()]


class ReplyBufferManager:
    """每会话的发送缓冲 + 抢话裁决。"""

    def __init__(self, plugin: Any):
        self._plugin = plugin
        self._queues: dict[str, list[dict[str, Any]]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = threading.Lock()
        self._records: list[dict[str, Any]] = []  # 裁决/发送记录（页面展示）
        self._speed_up: dict[str, bool] = {}
        self._interrupted: dict[str, str] = {}

    # ------------------------------------------------------------ 配置

    def _config(self) -> Any:
        return self._plugin.config

    def enabled(self) -> bool:
        return bool(self._config().bool("send.enabled", True))

    def judge_enabled(self) -> bool:
        return bool(self._config().bool("send.interrupt_judge_enabled", True))

    def _interval(self, item: dict[str, Any], *, speed_up: bool = False) -> float:
        if speed_up:
            return random.uniform(0.2, 0.4)
        try:
            lo = max(0.2, float(self._config().float("send.chunk_interval_min", 0.8)))
            hi = max(lo, float(self._config().float("send.chunk_interval_max", 4.0)))
        except Exception:
            lo, hi = 0.8, 4.0
        length = len(str(item.get("text") or ""))
        # 短句快（0.9s 起）、长句慢（2.5s 起），按比例映射
        ratio = min(1.0, length / 60.0)
        return random.uniform(lo + ratio * 0.4, lo + ratio * (hi - lo))

    # ------------------------------------------------------------ 提交与发送

    def submit(self, session_id: str, text: str, sender: Any = None) -> int:
        """把一条回复拆成缓存条目入队并启动后台发送；返回条数。"""
        text = (text or "").strip()
        if not text or not session_id:
            return 0
        parts = chunk_text(text)
        if not parts:
            return 0
        with self._lock:
            queue = self._queues.setdefault(session_id, [])
            for p in parts:
                queue.append({"text": p, "user": "", "sent": False, "at": _now_ts()})
            task = self._tasks.get(session_id)
        if task is None or task.done():
            self._tasks[session_id] = asyncio.ensure_future(self._drain(session_id))
        self._push_record(session_id, "queued", f"入缓存 {len(parts)} 条", parts=len(parts))
        return len(parts)

    async def _drain(self, session_id: str) -> None:
        """逐条发送队列；若期间用户抢话，暂停等待裁决结果。"""
        while True:
            item = None
            with self._lock:
                queue = self._queues.get(session_id)
                if not queue:
                    self._tasks.pop(session_id, None)
                    return
                item = queue[0]
            # 抢话裁决等待：用户消息到来 → on_interrupt 会标记 speed_up / 清空队列
            speed = bool(self._speed_up.get(session_id))
            delay = self._interval(item, speed_up=speed)
            await asyncio.sleep(delay)
            with self._lock:
                queue = self._queues.get(session_id)
                if not queue:
                    continue
                first = queue[0]
                if first is not item:
                    continue
                item = first
            ok = await self._send_item(session_id, item)
            with self._lock:
                queue = self._queues.get(session_id)
                if queue:
                    queue.pop(0)
            if ok:
                # 每条发送成功 → 回填记忆时间线（role=bot），保证记忆侧连续
                notifier = getattr(self._plugin, "_note_bot_reply_by_session", None)
                if callable(notifier):
                    try:
                        notifier(session_id, item["text"])
                    except Exception:
                        pass
                self._push_record(session_id, "sent", f"已发送：{item['text'][:40]}")
            else:
                # 发送失败：放弃该条，避免死循环（报错台由候选记录层负责）
                self._push_record(session_id, "send_failed", f"发送失败：{item['text'][:40]}")

    async def _send_item(self, session_id: str, item: dict[str, Any]) -> bool:
        try:
            from astrbot.api.event import MessageChain

            sender = getattr(self._plugin.context, "send_message", None)
            if not callable(sender) or not session_id:
                return False
            chain = MessageChain()
            text = str(item.get("text") or "")[:400]
            # 表情包占位符渲染（同图去重：按分类避开近 N 天已发）
            store = getattr(self._plugin, "emoji_store", None)
            user = str(item.get("user") or "")
            try:
                days = max(0, int(self._config().int("emoji.duplicate_days", 3) or 3))
            except Exception:
                days = 3
            segments = (
                store.render(text, dedup_days=days, user=user)
                if store is not None
                else [{"type": "text", "content": text}]
            )
            for seg in segments:
                if seg["type"] == "text" and seg.get("content"):
                    chain.message(seg["content"])
                elif seg["type"] == "emoji":
                    try:
                        chain.file_image(seg["path"])
                    except Exception:
                        pass
            await sender(session_id, chain)
            return True
        except Exception as exc:
            logger.warning("[Storyteller] 缓冲发送失败: %s", exc)
            return False

    # ------------------------------------------------------------ 抢话

    def has_pending(self, session_id: str) -> bool:
        with self._lock:
            queue = self._queues.get(session_id)
            return bool(queue)

    def on_user_message(self, event: Any) -> None:
        """用户消息钩子（on_message_observe 调用）：若缓存未发完 → 触发抢话裁决。"""
        session_id = str(getattr(event, "unified_msg_origin", "") or "")
        if not session_id or not self.has_pending(session_id):
            return
        if not self.enabled():
            return
        asyncio.ensure_future(self._interrupt(session_id, event))

    async def _interrupt(self, session_id: str, event: Any) -> None:
        if not self.judge_enabled():
            # 默认 A：提速发完，新消息正常一轮
            self._speed_up[session_id] = True
            self._push_record(session_id, "interrupt", "用户抢话：提速发完剩余（关闭裁决时默认）")
            return
        try:
            with self._lock:
                queue = self._queues.get(session_id)
                pending = [q["text"] for q in queue if not q["sent"]] if queue else []
            left = " ".join(pending)[:800]
            action, reason = await self._judge_interrupt(session_id, left, event)
            if action == "A":
                self._speed_up[session_id] = True
                self._push_record(session_id, "interrupt", f"判定 A（说完再回）：{reason}")
            else:
                with self._lock:
                    self._queues.pop(session_id, None)
                self._speed_up.pop(session_id, None)
                self._interrupted[session_id] = left[:600]
                self._push_record(session_id, "interrupt", f"判定 B（憋回去重新组织）：{reason}")
        except Exception as exc:
            logger.warning("[Storyteller] 抢话裁决异常: %s", exc)
            self._speed_up[session_id] = True

    async def _judge_interrupt(self, session_id: str, left: str, event: Any) -> tuple[str, str]:
        """A=说完再回；B=放弃剩余、带上下文重新组织。"""
        try:
            from .models import chat_text, resolve_chat_provider

            provider, provider_id = resolve_chat_provider(
                self._plugin.context, self._config(), "interrupt"
            )
            if provider is None:
                return "A", "裁决模型不可用，默认说完再回"
            user_text = str(getattr(event, "message_str", "") or "").strip()[:400]
            prompt = (
                "你是一个模拟真人聊天节奏的判断器。Bot 正在给用户发送一条分段消息（还没发完），"
                "此时用户抢话发了新消息。请判断 Bot 应该怎么处理，只输出 JSON："
                '{"action": "A" 或 "B", "reason": "一句话中文理由"}\n'
                "- A：尽快把剩余消息发完，再正常回应用户的新消息（像人说话被插话但话还没说完，说完再回应）；\n"
                "- B：放弃剩余消息，把它作为「没说完的话」连同用户新消息一起重新组织回应"
                "（像人被打断，发现对方有新说的，就放下刚才的话重新组织语言）。\n"
                f"Bot 还没发完的话：{left}\n"
                f"用户新消息：{user_text}\n"
                "判断依据：插话内容是否重要/是否改变了话题/刚才的话还剩多少；"
                "刚说到一半且插话是追问 → 多判 A；插话明显开启新话题或催促 → 多判 B。"
            )
            resp = await chat_text(provider, self._config(), prompt=prompt, session_id="storyteller_interrupt")
            self._plugin._record_usage(resp, "interrupt", provider_id or "default")
            raw = str(getattr(resp, "completion_text", "") or "")
            try:
                value = json.loads(raw.strip()[raw.find("{") : raw.rfind("}") + 1])
                action = str(value.get("action") or "A").strip().upper()
                reason = str(value.get("reason") or "")[:120]
                return ("A" if action in ("A", "A1") else ("B" if action in ("B", "B1") else "A")), reason
            except Exception:
                return "A", "裁决结果无法解析，默认说完再回"
        except Exception as exc:
            return "A", f"裁决调用失败：{str(exc)[:60]}"

    def take_interrupted_text(self, session_id: str) -> str:
        """取走 B 方案存下的「没说完的话」（生成时注入上下文；取走即清）。"""
        text = self._interrupted.pop(session_id, "") or ""
        if text:
            self._push_record(session_id, "context", "B 方案上下文已注入本轮生成")
        return text

    def pending_text(self, session_id: str) -> str:
        with self._lock:
            queue = self._queues.get(session_id)
            return " ".join(q["text"] for q in queue if not q.get("sent")) if queue else ""

    # ------------------------------------------------------------ 记录与面板

    def _push_record(self, session_id: str, kind: str, note: str, **extra: Any) -> None:
        entry = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "session_id": session_id or "",
            "kind": kind,
            "note": note[:200],
        }
        entry.update(extra)
        self._records.insert(0, entry)
        self._records = self._records[:60]

    def status(self) -> dict[str, Any]:
        with self._lock:
            queues = {
                sid: [
                    {"text": q.get("text"), "sent": bool(q.get("sent"))}
                    for q in queue[:10]
                ]
                for sid, queue in self._queues.items()
            }
        return {
            "enabled": self.enabled(),
            "judge_enabled": self.judge_enabled(),
            "queues": queues,
            "records": list(self._records[:30]),
            "interrupted": {k: v[:60] for k, v in self._interrupted.items()},
        }

    def purge(self, session_id: str = "") -> None:
        with self._lock:
            if session_id:
                self._queues.pop(session_id, None)
            else:
                self._queues.clear()
        for sid in list(self._tasks.keys()):
            t = self._tasks[sid]
            if not t.done():
                t.cancel()
        self._tasks.clear()

    def stop(self) -> None:
        self.purge()