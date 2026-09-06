"""消息防抖：把用户短时间内的连续消息合并为一条再交给主链处理。

设计要点（独立实现）：
- 按会话（unified_msg_origin）缓冲；窗口内新消息重置倒计时；
- 窗口内消息被静默（不触发 LLM）；到期后把合并内容写回锚事件并放行；
- 命令消息立即结算；撤回通知在窗口内移除对应消息；
- **智能判断（实验）**：取代固定时长/自适应时长——每次缓冲更新直连判定模型
  快速判断「对方是否已说完」：判定放行立即合并发送，判定继续则重新计时一轮等待，
  无更新到最终等待时长强制结算；判定模型不可用时回退固定窗口，不卡消息；
- 仅作用于「默认 LLM 请求链路」，不影响其他插件自行调用模型。
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from typing import Any

from .log import get_logger
from .models import chat_text, resolve_chat_provider

logger = get_logger("防抖")


def _now() -> float:
    try:
        return asyncio.get_running_loop().time()
    except RuntimeError:
        return time.monotonic()


def utc_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _clean_json_text(raw: str) -> str:
    """从 LLM 输出中提取 JSON 片段：剥 markdown 围栏、截取首个 { 到末个 }。"""
    text = (raw or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return ""
    return text[start:end + 1]


def parse_smart_judge(raw: str) -> dict[str, Any] | None:
    """解析智能判定结果：{"action": "release"|"continue", "reason": "..."}。"""
    try:
        value = json.loads(_clean_json_text(raw))
        if not isinstance(value, dict):
            return None
        action = str(value.get("action") or "").strip().lower()
        if action not in ("release", "continue"):
            return None
        return {"action": action, "reason": str(value.get("reason") or "")[:160]}
    except Exception:
        return None


class DebounceManager:
    """防抖管理器：会话缓冲、计时与结算（支持智能判断模式）。

    配置动态读取（持有插件引用而非 ConfigView 快照），
    保证设置页保存后立即生效。
    """

    def __init__(self, plugin: Any):
        self._plugin = plugin
        self._sessions: dict[str, dict[str, Any]] = {}
        self._history: list[dict[str, Any]] = []
        self._history_limit = 30
        self._smart_history: list[dict[str, Any]] = []   # 智能判定事件（面板展示）
        self._smart_limit = 30
        self._lock = threading.Lock()

    def _config(self) -> Any:
        return getattr(self._plugin, "config", None)

    # ------------------------------------------------------------- 配置

    def enabled(self) -> bool:
        return bool(self._config().bool("debounce.enabled", False))

    def _window(self) -> float:
        return max(0.3, float(self._config().float("debounce.window", 2.0)))

    def _adaptive(self) -> bool:
        return bool(self._config().bool("debounce.adaptive", True))

    def _min_wait(self) -> float:
        return max(0.2, float(self._config().float("debounce.min_wait", 1.0)))

    def _max_wait(self) -> float:
        return max(1.0, float(self._config().float("debounce.max_wait", 6.0)))

    def _max_total_wait(self) -> float:
        return max(2.0, float(self._config().float("debounce.max_total_wait", 12.0)))

    def _separator(self) -> str:
        return str(self._config().get("debounce.merge_separator", "\n"))

    def private_only(self) -> bool:
        return bool(self._config().bool("debounce.private_only", True))

    # ---- 智能判断（实验） ----

    def _smart_enabled(self) -> bool:
        return bool(self._config().bool("debounce.smart_judge", True))

    def _smart_quiet_wait(self) -> float:
        return max(1.0, float(self._config().float("debounce.smart_max_quiet_wait", 8.0)))

    def _smart_judge_timeout(self) -> float:
        """判定单次超时保护（0.148，默认 4s）：超时快速回退固定窗口，不阻塞防抖。"""
        try:
            return max(2.0, min(15.0, float(self._config().int("debounce.smart_judge_timeout", 4))))
        except (TypeError, ValueError):
            return 4.0

    def _smart_judge_min_interval(self) -> float:
        """两次判定最小间隔（0.148，默认 2.5s）：连续短消息不重复调用判定模型。"""
        try:
            return max(0.2, min(10.0, float(self._config().float("debounce.smart_judge_min_interval", 2.5))))
        except (TypeError, ValueError):
            return 2.5

    def _smart_context_enabled(self) -> bool:
        """「联动【为你篆刻的历史】插件取上下文」开关。"""
        return bool(self._config().bool("debounce.smart_use_context", False))

    def _smart_context_count(self) -> int:
        try:
            return max(1, min(20, self._config().int("debounce.smart_context_count", 4)))
        except (TypeError, ValueError):
            return 4

    def _smart_context(self, session: dict[str, Any]) -> str:
        """取该会话最近对话（【为你篆刻的历史】时间线/转述/文档总结）作为判定上下文。

        需要联动【为你篆刻的历史】插件：bridge 缺失/取不到时打印报错并跳过上下文（不阻塞判定）。
        上限：条数按配置、每条 ≤100 字、总预算 1500 字。
        """
        if not self._smart_context_enabled():
            return ""
        try:
            bridge = self._plugin._get_memory_bridge()
            if bridge is None:
                logger.error(
                    "智能判断: 已开启「联动【为你篆刻的历史】插件取上下文」，但未装载【为你篆刻的历史】插件"
                    "（无法取时间线），本次判定已跳过上下文"
                )
                return ""
            getter = getattr(bridge, "get_timeline", None)
            if not callable(getter):
                logger.error(
                    "智能判断: 已开启「联动【为你篆刻的历史】插件取上下文」，但【为你篆刻的历史】插件未提供 get_timeline"
                    "（版本过低或未联动），本次判定已跳过上下文"
                )
                return ""
            uid = str(session.get("uid") or "")
            parts = uid.split(":") if uid else []
            ctx: dict = {
                "session_id": uid,
                "platform": parts[0] if len(parts) > 0 else "",
            }
            events = getter(session_context=ctx, limit=self._smart_context_count())
            from .timeline_filter import is_llm_context_event

            lines: list[str] = []
            for ev in events or []:
                if not is_llm_context_event(ev):
                    continue
                text = ""
                if isinstance(ev, dict):
                    text = str(ev.get("content") or ev.get("text") or "").strip()
                elif hasattr(ev, "content"):
                    text = str(ev.content or "").strip()
                else:
                    text = str(ev or "").strip()
                if text:
                    lines.append(text[:100])
            if not lines:
                return ""
            joined = "\n".join(lines)
            return "「最近对话·【为你篆刻的历史】时间线」（用户说话/图片转述/文档总结）：\n" + joined[:1500]
        except Exception as exc:
            logger.warning("智能判断: 取上下文失败: %s（本次判定跳过上下文）", exc)
            return ""

    # ------------------------------------------------------------- 等待时长

    def _wait_for(self, text: str, session: dict[str, Any] | None) -> tuple[float, bool, str]:
        """计算下一轮等待：按内容形态自适应，返回 (等待秒, 是否立即结算, 原因)。"""
        if not self._adaptive():
            return self._window(), False, "fixed"
        clean = (text or "").strip()
        length = len(clean)
        reasons: list[str] = []
        if length <= 3:
            wait = 3.5
            reasons.append("very_short")
        elif length <= 10:
            wait = 2.8
            reasons.append("short")
        elif length <= 30:
            wait = 2.2
            reasons.append("medium")
        elif length <= 80:
            wait = 1.6
            reasons.append("long")
        else:
            wait = 1.0
            reasons.append("very_long")

        if clean.endswith(("...", "…", "，", "、", "：", ":")):
            wait += 1.5
            reasons.append("unfinished")
        elif clean.endswith(("？", "?")):
            wait -= 0.6
            reasons.append("question")
        elif clean.endswith(("。", "！", "!")):
            wait -= 0.4
            reasons.append("sentence_end")

        if session:
            if clean and len(clean) <= 10:
                session["short_streak"] = session.get("short_streak", 0) + 1
            else:
                session["short_streak"] = 0
            streak = session.get("short_streak", 0)
            if streak >= 4:
                wait += 0.7
                reasons.append("streak4")
            elif streak == 3:
                wait += 0.5
                reasons.append("streak3")
            elif streak == 2:
                wait += 0.3
                reasons.append("streak2")

        wait = max(self._min_wait(), min(wait, self._max_wait()))

        if session and session.get("started_at") is not None:
            elapsed = _now() - session["started_at"]
            remaining = self._max_total_wait() - elapsed
            if remaining <= 0:
                return 0.0, True, ",".join(reasons + ["total_limit"])
            if wait > remaining:
                wait = max(0.0, remaining)
                reasons.append("limited_total")
        return wait, False, ",".join(reasons) or "adaptive"

    # ------------------------------------------------------------- 会话管理

    def active_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "session_id": uid,
                    "count": len(session.get("items", [])),
                    "text_preview": (session.get("separator", "\n").join(session.get("buffer", [])))[:200],
                    "remaining": max(0.0, session.get("flush_at", 0.0) - _now()),
                    "started_at": session.get("started_at"),
                    "smart": self._smart_view(session),
                }
                for uid, session in self._sessions.items()
            ]

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history[-limit:][::-1])

    def smart_report(self, limit: int = 20) -> dict[str, Any]:
        """智能判定面板数据：判定事件 + 活动会话判定状态（含实时剩余秒）。"""
        with self._lock:
            entries = list(self._smart_history[-limit:][::-1])
            sessions = [
                {
                    "session_id": uid,
                    "count": len(session.get("items", [])),
                    "text_preview": (session.get("separator", "\n").join(session.get("buffer", [])))[:200],
                    "remaining": max(0.0, session.get("flush_at", 0.0) - _now()),
                    "smart": self._smart_view(session),
                }
                for uid, session in self._sessions.items()
            ]
        return {"entries": entries, "sessions": sessions}

    @staticmethod
    def _smart_view(session: dict[str, Any]) -> dict[str, Any]:
        """会话的智能判定状态摘要（供面板展示）。"""
        smart = session.get("smart") or {}
        judge_count = int(smart.get("judge_count", 0) or 0)
        judging = bool(smart.get("judging"))
        last_action = smart.get("last_action") or ""
        if judging:
            status = "判定中"
        elif judge_count == 0 or not session.get("flush_at"):
            status = "等待判定"
        elif last_action == "release":
            status = "已判定放行"
        else:
            status = "等待中"
        return {
            "enabled": bool(smart.get("enabled")),
            "judge_count": judge_count,
            "judging": judging,
            "last_action": last_action,
            "last_reason": smart.get("last_reason") or "",
            "status": status,
        }

    async def flush(self, session_id: str) -> bool:
        """手动立即结算某会话（唤醒等待中的处理器）；会话不存在返回 False。"""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            if session.get("timer"):
                session["timer"].cancel()
            flush_event = session.get("flush_event")
        if flush_event is not None:
            flush_event.set()
        return True

    async def flush_all(self) -> int:
        with self._lock:
            sessions = list(self._sessions.values())
            for session in sessions:
                if session.get("timer"):
                    session["timer"].cancel()
        count = 0
        for session in sessions:
            flush_event = session.get("flush_event")
            if flush_event is not None:
                flush_event.set()
                count += 1
        return count

    # ------------------------------------------------------------- 入口

    @staticmethod
    def _is_self_message(event: Any) -> bool:
        """识别平台回显的「机器人自己发出的消息」（sender == 自身 ID）。

        部分 OneBot 实现会把 Bot 发出的消息作为 message 事件回传；若不识别，
        会被当成对方消息收进防抖缓冲。默认平台不上报，此为双保险。
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

    async def handle(self, event: Any) -> bool:
        """处理一条消息：返回 True 表示已被防抖接管（静默），False 表示放行。

        首条消息：创建会话并阻塞等待结算（管道挂起），结算后重构锚事件并放行，
        由主链处理合并内容；窗口内后续消息：追加缓冲、重置计时并静默。
        智能判断模式：缓冲更新即直连判定模型，放行立即结算 / 继续则重新计时。
        """
        if not self.enabled():
            return False
        # 平台回显的自身消息：不参与防抖（放行，由主链与观察层各自防线处理）
        if self._is_self_message(event):
            return False
        # 通用兜底：事件已被其他处理器接管（命令系统/其他插件 set_result 或 stop）时一律放行
        try:
            get_result = getattr(event, "get_result", None)
            if callable(get_result) and get_result() is not None:
                return False
            is_stopped = getattr(event, "is_stopped", None)
            if callable(is_stopped) and is_stopped():
                return False
        except Exception:
            pass
        try:
            message_obj = getattr(event, "message_obj", None)
            if message_obj is None:
                return False
            uid = str(getattr(event, "unified_msg_origin", "") or "")
            if not uid:
                return False
            # 撤回通知：窗口内移除对应消息
            recalled = self._recall_message_id(event)
            if recalled:
                removed = self._remove_recalled(uid, recalled)
                logger.info("窗口内撤回消息: session=%s removed=%s", uid, removed)
                self._silence(event)
                return True
            # 仅私聊（可配置放宽）
            if self.private_only() and "group" in uid.lower():
                return False
            text, images, retained, segments = self._extract_content(event, message_obj)
            if not text and not images and not retained:
                return False
            # 命令判定：解析后的文本可能已被 AstrBot 剥离命令前缀（如 /reset -> reset），
            # 因此同时用原始消息文本（raw_message，保留斜杠）判断
            raw_text = self._raw_text(event, message_obj)
            if self._looks_command(text) or self._looks_command(raw_text):
                # 命令消息：丢弃防抖缓冲并唤醒等待结算，命令本身放行
                with self._lock:
                    session = self._sessions.pop(uid, None)
                if session is not None:
                    if session.get("timer"):
                        session["timer"].cancel()
                    session["buffer"] = []
                    session["images"] = []
                    session["retained"] = []
                    session["segments"] = []
                    session["items"] = []
                    flush_event = session.get("flush_event")
                    if flush_event is not None:
                        flush_event.set()
                logger.info("遇命令消息，丢弃缓冲: session=%s text=%s raw=%s", uid, text[:50], raw_text[:50])
                return False
            message_id = self._message_id(event, message_obj)
            now = _now()
            with self._lock:
                session = self._sessions.get(uid)
                if session is not None:
                    # 窗口内追加并重置计时，随后静默
                    session["items"].append({"message_id": message_id, "text": text, "images": images, "retained": retained, "segments": segments})
                    if text:
                        session["buffer"].append(text)
                    if images:
                        session["images"].extend(images)
                    if retained:
                        session.setdefault("retained", []).extend(retained)
                    session.setdefault("segments", []).extend(segments)
                    if session.get("timer") and not self._smart_enabled():
                        session["timer"].cancel()
                    self._silence(event)
                    if self._smart_enabled():
                        # 智能判断（0.150 提速）：每条消息重置一个「快速确认窗口」（默认 3s），
                        # 最后一句话后很快结算——不再被判定 continue 拖满 8s×N（用户实测 34s 元凶）；
                        # 判定仍在后台跑：release 可提前结算，判定慢/失败由窗口兜底，判定只减时不加时。
                        if session.get("timer"):
                            session["timer"].cancel()
                        wait = self._smart_quiet_wait()
                        session["flush_at"] = now + wait
                        session["timer"] = asyncio.ensure_future(self._timer(uid, wait))
                        smart_judge = True
                    else:
                        wait, flush_now, reason = self._wait_for(text, session)
                        session["last_wait"] = wait
                        session["last_reason"] = reason
                        if not flush_now:
                            session["flush_at"] = now + wait
                            session["timer"] = asyncio.ensure_future(self._timer(uid, wait))
                        smart_judge = False
                        smart_reason = reason
                    appended = True
                else:
                    appended = False

            if appended:
                if smart_judge:
                    logger.info(
                        "收集(追加): session=%s items=%s -> 触发智能判断",
                        uid, len(session["items"]),
                    )
                    asyncio.ensure_future(self._smart_judge(session))
                else:
                    logger.info(
                        "收集(追加): session=%s wait=%.2fs reason=%s",
                        uid, wait, smart_reason,
                    )
                return True

            # 首条消息：创建会话并阻塞等待结算（锚事件为本条消息）
            flush_event = asyncio.Event()
            if self._smart_enabled():
                wait = self._smart_quiet_wait()
                reason = "smart"
            else:
                wait, _, reason = self._wait_for(text, None)
            smart_state = {"enabled": True, "judge_count": 0, "judging": False, "last_action": "", "last_reason": ""} if self._smart_enabled() else {}
            session = {
                "uid": uid,
                "anchor_event": event,
                "items": [{"message_id": message_id, "text": text, "images": images, "retained": retained, "segments": segments}],
                "buffer": [text] if text else [],
                "images": list(images),
                "retained": list(retained),
                "segments": list(segments),
                "flush_event": flush_event,
                "timer": None,
                "started_at": now,
                "flush_at": now + wait,
                "last_wait": wait,
                "last_reason": reason,
                "short_streak": 1 if text and len(text.strip()) <= 10 else 0,
                "smart": smart_state,
            }
            self._sessions[uid] = session
            if self._smart_enabled():
                logger.info("收集(首条): session=%s -> 触发智能判断（初始判定）", uid)
                # 兜底计时：判定期间若长时间无结果，到 point 强制结算（判定会更新计时）
                session["timer"] = asyncio.ensure_future(self._timer(uid, wait))
                asyncio.ensure_future(self._smart_judge(session, initial=True))
            else:
                session["timer"] = asyncio.ensure_future(self._timer(uid, wait))
                logger.info("收集(首条): session=%s wait=%.2fs reason=%s", uid, wait, reason)
            # 阻塞等待结算：计时器或命令/手动/判定放行触发
            await flush_event.wait()
            with self._lock:
                self._sessions.pop(uid, None)
            await self._settle(session)
            return False  # 放行：管道继续，主链处理合并内容
        except Exception as exc:
            logger.warning("防抖处理异常: %s", exc, exc_info=True)
            return False

    # ------------------------------------------------------------- 智能判断

    def _smart_prompt(self, session: dict[str, Any]) -> str:
        """构造智能判定提示词：基于当前缓冲内容 +（可选）会话上下文呼应。"""
        merged = self._separator().join(session.get("buffer", [])).strip()
        count = len(session.get("items", []))
        rounds = int((session.get("smart") or {}).get("judge_count", 0) or 0)
        # 联动【为你篆刻的历史】插件：携带该会话最近对话（时间线/转述/总结），与缓冲内容共用 1500 字预算
        context_block = self._smart_context(session)
        merged_budget = max(200, 1500 - len(context_block))
        preview = merged[:merged_budget]
        lines = [
            "你是消息防抖组件里的快速判断器。对方正在陆续发消息，下面是当前这一轮已经收集到的内容。\n"
            "请判断：对方是已经说完了（内容完整、可以回复了），还是仍在陆续输入、应该继续等待合并？\n"
            "只输出一个 JSON 对象，不要任何解释或代码块标记；reason 一句话 ≤10 字："
            '{"action": "release" 或 "continue", "reason": "一句话中文理由"}\n'
            "- release：内容已经完整、表达已经收尾，再等下去也不太可能有新补充，应立刻发给主模型回复；\n"
            "- continue：明显还没说完（话没讲完、连续短句还在追加、语气未完），应继续等待、把后续内容并入。\n"
            "要克制：不确定时优先 continue，避免拆散对方的话；但也别无限等，对方已经停顿或内容自洽时放行。\n\n",
        ]
        if context_block:
            lines.append(f"{context_block}\n")
        lines.append(
            f"这是第 {rounds} 次判断；已收集 {count} 条消息，当前内容：\n{preview or '（仅图片，无文字）'}"
        )
        return "\n".join(lines)

    def _push_smart_entry(
        self,
        uid: str,
        kind: str,
        *,
        action: str = "",
        reason: str = "",
        raw: str = "",
        prompt: str = "",
    ) -> None:
        entry = {
            "time": utc_now(),
            "session_id": uid or "",
            "kind": kind,                     # request / result / fallback / timeout
            "action": action,
            "reason": (reason or "")[:200],
            "raw": (raw or "")[:300],
            "prompt": (prompt or "")[:600],
        }
        with self._lock:
            self._smart_history.append(entry)
            if len(self._smart_history) > self._smart_limit:
                del self._smart_history[: len(self._smart_history) - self._smart_limit]

    def _schedule_smart_wait(self, session: dict[str, Any], uid: str) -> None:
        """判定继续等待：重新取得完整一轮等待（无更新到点强制结算）。"""
        wait = self._smart_quiet_wait()
        with self._lock:
            if session.get("timer"):
                session["timer"].cancel()
            session["flush_at"] = _now() + wait
            session["timer"] = asyncio.ensure_future(self._timer(uid, wait))
        logger.info(
            "智能判断: 判定继续等待，重置等待 %.1fs（无更新到点强制结算）session=%s",
            wait, uid,
        )

    def _fallback_wait(self, session: dict[str, Any], uid: str, reason: str) -> None:
        """模型不可用/超时/失败：回退固定窗口等待后结算（不卡消息）。"""
        fallback = self._window()
        with self._lock:
            if session.get("timer"):
                session["timer"].cancel()
            session["flush_at"] = _now() + fallback
            session["timer"] = asyncio.ensure_future(self._timer(uid, fallback))
        logger.warning("智能判断: %s，回退固定窗口 %.1fs 后结算 session=%s", reason, fallback, uid)

    async def _smart_judge(self, session: dict[str, Any], *, initial: bool = False) -> None:
        """智能判定：直连判定模型快速判断「放行/继续」。

        判定放行 -> 立即唤醒结算；判定继续 -> 重新计时完整等待（每次判定后刷新）；
        模型不可用/超时/失败 -> 回退固定窗口；并发判定用 judging 标志防重入。
        """
        uid = str(session.get("uid") or "")
        smart = session.setdefault(
            "smart",
            {"enabled": True, "judge_count": 0, "judging": False, "last_action": "", "last_reason": ""},
        )
        if smart.get("judging"):
            return  # 已有判定在途，跳过本次（防并发重复请求）
        # 0.148 节流：距上次判定不足最小间隔（连续短消息），跳过本次调用（不重复消耗与等待）
        last_at = float(smart.get("last_judge_at", 0) or 0)
        now_ms = time.monotonic()
        if last_at and (now_ms - last_at) < self._smart_judge_min_interval():
            return
        smart["judging"] = True
        smart["last_judge_at"] = now_ms
        try:
            smart["judge_count"] = int(smart.get("judge_count", 0) or 0) + 1
            prompt = self._smart_prompt(session)
            merged = self._separator().join(session.get("buffer", [])).strip()
            self._push_smart_entry(uid, "request", prompt=prompt)
            logger.info(
                "智能判断: 缓冲更新后请求判定 session=%s items=%s len=%s（第 %s 次）",
                uid, len(session.get("items", [])), len(merged), smart["judge_count"],
            )
            provider, provider_id = resolve_chat_provider(
                self._plugin.context, self._plugin.config, "smart_judge"
            )
            if provider is None:
                # 模型已驳回（models 模块已输出报错日志）
                self._push_smart_entry(uid, "fallback", action="fallback", reason="判定模型不可用（已驳回）")
                self._fallback_wait(session, uid, "判定模型不可用，请求被驳回")
                smart["last_action"] = "fallback"
                smart["last_reason"] = "判定模型不可用"
                return
            try:
                resp = await asyncio.wait_for(
                    chat_text(
                        provider,
                        self._plugin.config,
                        prompt=prompt,
                        session_id="storyteller_debounce_smart",
                    ),
                    timeout=self._smart_judge_timeout(),
                )
            except asyncio.TimeoutError:
                self._push_smart_entry(uid, "timeout", action="fallback", reason="判定超时")
                smart["last_action"] = "fallback"
                smart["last_reason"] = "判定超时"
                self._fallback_wait(session, uid, "判定请求超时")
                return
            except Exception as exc:
                self._push_smart_entry(uid, "fallback", action="fallback", reason=f"判定调用失败: {exc}")
                smart["last_action"] = "fallback"
                smart["last_reason"] = "判定调用失败"
                self._fallback_wait(session, uid, f"判定调用失败: {exc}")
                return
            raw = str(getattr(resp, "completion_text", "") or "").strip()
            parsed = parse_smart_judge(raw)
            if parsed is None:
                logger.warning("智能判断: 判定结果无法解析: %.100r（按继续等待处理一轮）", raw)
                self._push_smart_entry(uid, "result", action="continue", reason="结果无法解析，保守继续", raw=raw)
                smart["last_action"] = "continue"
                smart["last_reason"] = "结果无法解析，保守继续"
                self._schedule_smart_wait(session, uid)
                return
            action = parsed["action"]
            reason = parsed["reason"]
            smart["last_action"] = action
            smart["last_reason"] = reason
            self._push_smart_entry(uid, "result", action=action, reason=reason, raw=raw)
            logger.info(
                "智能判断: 判定结果 action=%s reason=%s session=%s",
                action, reason or "-", uid,
            )
            if action == "release":
                # 判定放行：立即结算（取消兜底计时，唤醒阻塞的 handle）
                with self._lock:
                    if session.get("timer"):
                        session["timer"].cancel()
                flush_event = session.get("flush_event")
                if flush_event is not None:
                    flush_event.set()
                return
            self._schedule_smart_wait(session, uid)
        except Exception as exc:
            logger.warning("智能判断: 判定流程异常: %s", exc)
            self._fallback_wait(session, uid, f"判定流程异常: {exc}")
        finally:
            smart["judging"] = False

    # ------------------------------------------------------------- 计时与结算

    async def _timer(self, uid: str, duration: float) -> None:
        """计时器：到时唤醒等待结算的处理器（结算由阻塞的 handle 执行）。"""
        try:
            await asyncio.sleep(duration)
            with self._lock:
                session = self._sessions.get(uid)
            if session is not None:
                flush_event = session.get("flush_event")
                if flush_event is not None:
                    flush_event.set()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("防抖计时异常: %s", exc)

    async def _settle(self, session: dict[str, Any]) -> None:
        """结算：合并缓冲内容，恢复锚事件传播后放行（不静默）。"""
        try:
            anchor = session.get("anchor_event")
            buffer_text = session.get("buffer", [])
            images = session.get("images", [])
            retained = session.get("retained", [])
            merged = self._separator().join(buffer_text).strip()
            if not merged and not images and not retained:
                logger.info("结算: 无内容，静默丢弃 session=%s", session.get("uid"))
                if anchor is not None:
                    self._silence(anchor)
                return
            if anchor is not None:
                # 锚事件此前被静默（stop + 禁止 LLM），结算时全部恢复
                try:
                    continue_event = getattr(anchor, "continue_event", None)
                    if callable(continue_event):
                        continue_event()
                except Exception:
                    pass
                try:
                    should_call_llm = getattr(anchor, "should_call_llm", None)
                    if callable(should_call_llm):
                        should_call_llm(False)  # 恢复默认 LLM 请求（静默时置为 True 禁止）
                except Exception:
                    pass
                self._reconstruct(anchor, merged, images, retained, session.get("segments") or [])
            self._push_history(session.get("uid"), len(session.get("items", [])), merged, images)
            logger.info(
                "结算: session=%s items=%s -> 合并发送（%s 字）",
                session.get("uid"), len(session.get("items", [])), len(merged),
            )
        except Exception as exc:
            logger.warning("防抖结算异常: %s", exc)

    def _push_history(self, uid: str, count: int, text: str, images: list) -> None:
        entry = {
            "time": utc_now(),
            "session_id": uid or "",
            "count": count,
            "text": text[:400],
            "image_count": len(images or []),
        }
        with self._lock:
            self._history.append(entry)
            if len(self._history) > self._history_limit:
                del self._history[: len(self._history) - self._history_limit]

    # ------------------------------------------------------------- 工具

    @staticmethod
    def _silence(event: Any) -> None:
        """静默事件：阻止默认 LLM 请求链路并终止传播。"""
        try:
            call_llm = getattr(event, "should_call_llm", None)
            if callable(call_llm):
                call_llm(True)
        except Exception:
            pass
        try:
            clear = getattr(event, "clear_result", None)
            if callable(clear):
                clear()
        except Exception:
            pass
        try:
            stop = getattr(event, "stop_event", None)
            if callable(stop):
                stop()
        except Exception:
            pass

    @staticmethod
    def _recall_message_id(event: Any) -> str:
        try:
            message_obj = getattr(event, "message_obj", None)
            if message_obj is None:
                return ""
            raw = getattr(message_obj, "raw_message", None)
            if not isinstance(raw, dict):
                return ""
            if raw.get("post_type") != "notice":
                return ""
            if raw.get("notice_type") not in ("group_recall", "friend_recall"):
                return ""
            return str(raw.get("message_id") or "")[:120]
        except Exception:
            return ""

    def _remove_recalled(self, uid: str, recalled_mid: str) -> int:
        with self._lock:
            session = self._sessions.get(uid)
            if session is None:
                return 0
            before = len(session["items"])
            session["items"] = [
                item for item in session["items"]
                if str(item.get("message_id") or "") != recalled_mid
            ]
            removed = before - len(session["items"])
            if removed:
                session["buffer"] = [item["text"] for item in session["items"] if item.get("text")]
                session["images"] = [url for item in session["items"] for url in item.get("images", [])]
                session["retained"] = [c for item in session["items"] for c in item.get("retained", [])]
                session["segments"] = [seg for item in session["items"] for seg in item.get("segments", [])]
                if not session["items"]:
                    session.pop("uid", None)
                    self._sessions.pop(uid, None)
                    if session.get("timer"):
                        session["timer"].cancel()
            return removed

    @staticmethod
    def _extract_content(event: Any, message_obj: Any) -> tuple[str, list[str], list, list]:
        """提取文本、图片 URL、需保留的媒体组件（File/Share/Video/Record/无 url 的 Face）与保序片段。

        0.169 起额外返回 segments（原始顺序的文本/媒体交错片段）：
        {"kind": "text"|"image"|"face"|"file"|"share"|"video"|"record", "text"/"url"/"component"}——
        多条连发里的媒体位置（"帮我看看这个/[文档]/算了不用了"）此前在合并重建时丢失，
        会意与语义因此错位（用户实测场景）。
        """
        text = str(getattr(event, "message_str", "") or "")
        if not text:
            getter = getattr(event, "get_message_str", None)
            if callable(getter):
                try:
                    value = getter()
                    if value:
                        text = str(value)
                except Exception:
                    pass
        if not text:
            # 兜底：从消息对象提取文本
            text = str(getattr(message_obj, "message_str", "") or "")
        images: list[str] = []
        retained: list = []
        segments: list = []
        try:
            chain = getattr(message_obj, "message", None)
            if isinstance(chain, list):
                for comp in chain:
                    cls = type(comp).__name__
                    if cls in ("Image", "Face"):
                        url = str(getattr(comp, "url", "") or getattr(comp, "file", "") or "")
                        if url:
                            images.append(url[:500])
                            segments.append({"kind": "image", "url": url[:500]})
                        else:
                            retained.append(comp)
                            segments.append({"kind": "face", "component": comp})
                    elif cls in ("File", "Share", "Video", "Record"):
                        retained.append(comp)
                        segments.append({"kind": cls.lower(), "component": comp})
                    elif cls == "Plain":
                        part = str(getattr(comp, "text", "") or "")
                        if part:
                            if not text:
                                text = part
                            segments.append({"kind": "text", "text": part})
        except Exception:
            pass
        return text.strip(), images, retained, segments

    def _command_prefixes(self) -> tuple[str, ...]:
        """可配置的命令前缀列表（默认 '/'）：以这些前缀开头的消息识别为命令，不参与防抖合并。"""
        raw = str(self._config().get("debounce.command_prefixes", "/") or "/")
        parts = [item for item in raw.replace(",", " ").split() if item]
        return tuple(parts) or ("/",)

    @staticmethod
    def _strip_decorations(value: str) -> str:
        current = value.strip()
        for _ in range(8):
            previous = current
            current = re.sub(
                r"^(?:\[CQ:at,[^\]]+\]|\[At:[^\]]+\]|\[at:[^\]]+\])\s*", "", current, flags=re.I
            )
            current = re.sub(
                r"^(?:\[Reply:[^\]]+\]|\[reply:[^\]]+\]|\[引用消息[^\]]*\])\s*", "", current, flags=re.I
            )
            current = re.sub(r"^@\S{1,64}\s+", "", current)
            current = re.sub(r"^<at\b[^>]*>\s*", "", current, flags=re.I)
            if current == previous:
                break
        return current.strip()

    def _looks_command(self, text: str) -> bool:
        """命令识别：以配置的命令前缀开头（支持剥离 @/引用/CQ 装饰后判断）。"""
        stripped = (text or "").strip()
        if not stripped:
            return False
        prefixes = self._command_prefixes()
        candidates = (stripped, self._strip_decorations(stripped))
        return any(candidate.startswith(prefixes) for candidate in candidates)

    @staticmethod
    def _raw_text(event: Any, message_obj: Any) -> str:
        """从原始消息（raw_message）提取未剥离前缀的文本（OneBot 原始字符串）。"""
        try:
            raw = getattr(message_obj, "raw_message", None)
            if isinstance(raw, dict):
                value = raw.get("raw_message") or raw.get("raw_text")
                if isinstance(value, str) and value.strip():
                    return value.strip()
        except Exception:
            pass
        return ""

    @staticmethod
    def _message_id(event: Any, message_obj: Any) -> str:
        for source in (message_obj, event):
            if source is None:
                continue
            value = getattr(source, "message_id", None) or getattr(source, "id", None)
            if value:
                return str(value)[:120]
        return ""

    @staticmethod
    def _reconstruct(event: Any, merged_text: str, images: list[str], retained: list = None, segments: list = None, separator: str = "\n") -> None:
        """把合并内容写回锚事件：替换消息链与文本，使其按正常链路发送给 LLM。

        保留组件（File/Share/Video/Record/无 url 表情）原样拼回消息链，
        避免分条发送时文件/链接在防抖合并中被丢弃。
        0.169：有 segments 时按原始顺序重建（文本与媒体交错位置保留——
        "帮我看看这个/[文档]/算了不用了" 顺序不再错位）；无 segments 回退旧结构。
        """
        message_obj = getattr(event, "message_obj", None)
        if message_obj is None:
            return
        try:
            chain = []
            try:
                from astrbot.api.message_components import Plain

                if merged_text and not segments:
                    chain.append(Plain(text=merged_text))
            except Exception as imp_exc:
                # 组件导入失败（平台/版本差异）：退化为直接写文本属性，保证主链拿得到合并内容
                logger.warning("防抖重构: 组件导入失败，退化纯文本写入: %s", imp_exc)
                try:
                    message_obj.message_str = merged_text
                except Exception:
                    pass
                try:
                    event.message_str = merged_text
                except Exception:
                    pass
                return
            if segments:
                # 保序重建：连续文本合并为一个 Plain，媒体片段插在对应位置
                buf_text: list[str] = []

                def flush_text() -> None:
                    if buf_text:
                        joined = separator.join(buf_text).strip()
                        if joined:
                            chain.append(Plain(text=joined))
                        buf_text.clear()

                try:
                    from astrbot.api.message_components import Image

                    for seg in segments:
                        kind = seg.get("kind")
                        if kind == "text":
                            buf_text.append(str(seg.get("text") or ""))
                        elif kind == "image":
                            flush_text()
                            url = str(seg.get("url") or "")
                            if url:
                                try:
                                    chain.append(Image.fromURL(url))
                                except Exception:
                                    chain.append(Image(file=url))
                        else:
                            flush_text()
                            comp = seg.get("component")
                            if comp is not None:
                                try:
                                    chain.append(comp)
                                except Exception:
                                    pass
                    flush_text()
                except Exception:
                    pass
                # 兜底：链异常为空 → 用图片/保留组件补充
                if not any(getattr(c, "text", "") for c in chain):
                    try:
                        from astrbot.api.message_components import Image

                        for url in images:
                            try:
                                chain.append(Image.fromURL(url))
                            except Exception:
                                chain.append(Image(file=url))
                    except Exception:
                        pass
                    for comp in retained or []:
                        try:
                            chain.append(comp)
                        except Exception:
                            pass
            else:
                try:
                    from astrbot.api.message_components import Image

                    for url in images:
                        try:
                            chain.append(Image.fromURL(url))
                        except Exception:
                            chain.append(Image(file=url))
                except Exception:
                    pass
                for comp in retained or []:
                    try:
                        chain.append(comp)
                    except Exception:
                        pass
            message_obj.message = chain
            message_obj.message_str = merged_text
            if hasattr(event, "message_str"):
                try:
                    event.message_str = merged_text
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("防抖重构事件失败: %s", exc)
            # 兜底：至少把合并文本写回事件（主链可见）
            try:
                event.message_str = merged_text
                message_obj.message_str = merged_text
            except Exception:
                pass