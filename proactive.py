"""主动对话：智能的、更像人的主动触达。

设计要点（独立实现，不与外部插件雷同）：
- 主动消息不是随机定时器，而是「有由头」的念头——从状态、日程、记忆里的约定/愿望取材；
- 时间窗 + 随机间隔 + 每日上限；
- 刚聊完顺延、未回应降速（克制打扰，宁可不说也不轰炸）；
- LLM 生成正文（带由头），发送前本地校验。
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from typing import Any

from .log import logger
from .persona import extract_sender
from .inspiration import daypart_bucket


def _now_ts() -> float:
    return time.time()


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def _hhmm() -> str:
    return time.strftime("%H:%M", time.localtime())


def _minutes_hm(hhmm: str) -> int:
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 0


class ProactiveManager:
    """主动触达管理器：候选来源 + 边界 + 生成 + 发送。

    未回应动态机制（0.118）：每用户维护连续未回应计数；发送越多未被理睬，
    间隔越长、话题越轻、温度越冷，超过静默闸门后暂停普通主动（优先于每日上限），
    等对方先开口；用户回复即全部归位。
    """

    def __init__(self, plugin: Any):
        self._plugin = plugin
        self._loop_task: asyncio.Task | None = None
        self._last_sent: dict[str, float] = {}
        self._last_interaction: dict[str, float] = {}
        self._daily_count: dict[str, int] = {}
        self._daily_per_user: dict[str, int] = {}
        self._candidates: list[dict[str, Any]] = []
        self._sent_history: list[dict[str, Any]] = []
        self._user_state: dict[str, dict[str, Any]] = {}
        self._user_state_path = None
        try:
            data_dir = getattr(plugin, "data_dir", None)
            if data_dir is not None:
                from pathlib import Path

                self._user_state_path = Path(data_dir) / "proactive_user_state.json"
        except Exception:
            self._user_state_path = None
        self._load_user_state()
        self._load_meta()

    # ------------------------------------------------------------ 未回应状态存取

    def _load_user_state(self) -> None:
        """加载每用户未回应状态（重启后延续「还在等你回话」的记忆）。"""
        if self._user_state_path is None:
            return
        try:
            import json as _json

            if self._user_state_path.exists():
                raw = _json.loads(
                    self._user_state_path.read_text(encoding="utf-8") or "{}"
                )
                if isinstance(raw, dict):
                    self._user_state = {
                        str(k): (v if isinstance(v, dict) else {})
                        for k, v in raw.items()
                    }
        except Exception:
            self._user_state = {}

    # ------------------------------------------------------------ 0.231 频控元数据落盘
    #
    # 背景：`_daily_count` / `_last_sent` 此前是**纯内存**字典 —— 插件每次重载（AstrBot 重启、
    # 更新插件、面板重载）都会归零，于是 `proactive.max_daily`（默认 3）形同虚设：
    # 同一自然日里重载几次就可能多发几轮。这里把它们落到与 user_state 同目录的 proactive_meta.json。

    def _meta_path(self) -> Any:
        if self._user_state_path is None:
            return None
        return self._user_state_path.parent / "proactive_meta.json"

    def _load_meta(self) -> None:
        path = self._meta_path()
        if path is None or not path.exists():
            return
        try:
            import json as _json

            raw = _json.loads(path.read_text(encoding="utf-8") or "{}")
            if not isinstance(raw, dict):
                return
            daily = raw.get("daily")
            if isinstance(daily, dict):
                self._daily_count = {str(k): int(v or 0) for k, v in daily.items()}
            sent = raw.get("last_sent")
            if isinstance(sent, dict):
                self._last_sent = {str(k): float(v or 0) for k, v in sent.items()}
        except Exception:
            pass

    def _save_meta(self) -> None:
        path = self._meta_path()
        if path is None:
            return
        try:
            import json as _json

            # 只保留最近 7 天的每日计数，避免无限增长
            cutoff = time.strftime("%Y-%m-%d", time.localtime(_now_ts() - 7 * 86400))
            daily = {k: v for k, v in self._daily_count.items() if str(k) >= cutoff}
            self._daily_count = daily
            path.write_text(
                _json.dumps({"daily": daily, "last_sent": self._last_sent},
                            ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _save_user_state(self) -> None:
        if self._user_state_path is None:
            return
        try:
            import json as _json

            self._user_state_path.write_text(
                _json.dumps(self._user_state, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _user_state_for(self, user: str) -> dict[str, Any]:
        st = self._user_state.setdefault(str(user), {})
        st.setdefault("streak", 0)
        st.setdefault("awaiting_since", 0.0)
        st.setdefault("last_reply_at", 0.0)
        st.setdefault("last_sent_at", 0.0)
        st.setdefault("mood_linked", False)
        return st

    def user_state_view(self, user: str) -> dict[str, Any]:
        """只读视图（面板展示）。"""
        st = self._user_state_for(user)
        return {
            "streak": max(0, int(st.get("streak", 0) or 0)),
            "awaiting_since": st.get("awaiting_since") or 0,
            "last_reply_at": st.get("last_reply_at") or 0,
            "silenced": bool(self._silence_blocked(user)),
        }

    def _cfg_int(self, key: str, default: int) -> int:
        try:
            return max(0, int(self._config().int(f"proactive.{key}", default)))
        except Exception:
            return default

    def _cfg_float(self, key: str, default: float) -> float:
        try:
            return max(1.0, float(self._config().float(f"proactive.{key}", default)))
        except Exception:
            return default

    # ------------------------------------------------------------ 未回应动态机制

    def _unanswered_interval_multiplier(self, streak: int) -> float:
        """连续未回应 → 下次主动间隔放大倍数。

        超出阈值后每多一次 +0.35，封顶 unanswered_max_interval_multiplier。
        """
        start = self._cfg_int("unanswered_slowdown_start", 2)
        active = max(0, int(streak) - start + 1)
        max_mult = self._cfg_float("unanswered_max_interval_multiplier", 2.2)
        return min(max_mult, 1.0 + active * 0.35)

    def _silence_blocked(self, user: str) -> str:
        """静默闸门：连续未回应够多且悬置够久 → 暂停普通主动（优先于每日上限）。

        返回空串 = 不挡；否则返回原因。
        """
        st = self._user_state_for(user)
        streak = max(0, int(st.get("streak", 0) or 0))
        if streak <= 0:
            return ""
        need_streak = self._cfg_int("silent_after_streak", 3)
        need_hours = self._cfg_float("silent_after_hours", 24.0)
        awaiting = float(st.get("awaiting_since", 0) or 0)
        if streak >= need_streak and awaiting > 0:
            pending_hours = (_now_ts() - awaiting) / 3600.0
            if pending_hours >= need_hours:
                return f"对方已连续 {streak} 次未回应、悬置超过 {need_hours:g} 小时——暂停普通主动，等对方先开口"
        return ""

    def _temperature(self, user: str) -> dict[str, Any]:
        """当前关系温度：未回应扣分 / 最近回应加成 / 上一轮还悬着 / 心情偏收。"""
        st = self._user_state_for(user)
        streak = max(0, int(st.get("streak", 0) or 0))
        score = 0.54
        reasons: list[str] = []
        if streak:
            score -= min(0.32, streak * 0.08)
            reasons.append(f"未回应 {streak} 次")
        last_reply = float(st.get("last_reply_at", 0) or 0)
        if last_reply > 0:
            hours = max(0.0, (_now_ts() - last_reply) / 3600.0)
            if hours <= 6:
                score += 0.12
                reasons.append("刚有回应")
            elif hours <= 24:
                score += 0.06
                reasons.append("近一天回应过")
        awaiting = float(st.get("awaiting_since", 0) or 0)
        if awaiting > 0 and _now_ts() - awaiting > 4 * 3600:
            score -= 0.08
            reasons.append("上一轮还悬着")
        # Bot 心情偏收也降温（与 presence 心情联动）
        try:
            presence = self._plugin.presence_store.load()
            mood = str(presence.get("mood") or "").strip()
            tone = float(presence.get("tone") or 0.0)
            if mood in ("低落", "疲惫", "沮丧", "失落") or tone < -0.3:
                score -= 0.08
                reasons.append("心情偏收")
        except Exception:
            pass
        score = max(0.05, min(1.0, score))
        if score >= 0.7:
            label = "温热"
        elif score <= 0.38:
            label = "偏冷"
        else:
            label = "普通"
        return {"score": round(score, 3), "label": label, "detail": "；".join(reasons[:5]) or "回应节奏平稳"}

    def _advance_unanswered_state(self, user: str) -> dict[str, Any]:
        """发送完成后推进未回应状态：上次发送后没回 → streak+1、悬置计时、心情联动。

        返回 {"streak": n, "mood_triggered": bool}（供候选记录与日志）。
        """
        st = self._user_state_for(user)
        last_reply = self._last_interaction.get(user) or 0
        last_sent_before = self._last_sent.get(user) or 0
        if last_sent_before <= 0 or last_reply >= last_sent_before:
            return {"streak": int(st.get("streak", 0) or 0), "mood_triggered": False}
        st["streak"] = int(st.get("streak", 0) or 0) + 1
        if not st.get("awaiting_since"):
            st["awaiting_since"] = _now_ts()
        st["last_sent_at"] = _now_ts()
        mood_triggered = False
        mood_on = self._config().bool("proactive.mood_link", True)
        if mood_on and not st.get("mood_linked"):
            need = self._cfg_int("mood_down_streak", 2)
            if int(st.get("streak", 0)) >= need:
                downer = getattr(self._plugin, "_note_proactive_unanswered", None)
                if callable(downer):
                    try:
                        downer(user)
                        st["mood_linked"] = True
                        mood_triggered = True
                    except Exception:
                        pass
        self._save_user_state()
        return {"streak": int(st.get("streak", 0) or 0), "mood_triggered": mood_triggered}

    # ------------------------------------------------------------ 候选记录与面板

    def _record_candidate(self, entry: dict[str, Any]) -> None:
        """记录一次主动候选的完整判定过程（供面板展示）。"""
        entry.setdefault("time", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        self._candidates.insert(0, entry)
        if len(self._candidates) > 60:
            self._candidates = self._candidates[:60]

    def candidates(self) -> list[dict[str, Any]]:
        return list(self._candidates)

    def _record_sent(self, user: str, text: str) -> None:
        entry = {
            "user": user,
            "text": text[:300],
            "at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        }
        self._sent_history.insert(0, entry)
        if len(self._sent_history) > 60:
            self._sent_history = self._sent_history[:60]

    def sent_history(self) -> list[dict[str, Any]]:
        return list(self._sent_history)

    def _config(self) -> Any:
        return self._plugin.config

    def enabled(self) -> bool:
        if not self._config().bool("proactive.enabled", False):
            return False
        start = str(self._config().get("proactive.time_start", "09:00") or "09:00")
        end = str(self._config().get("proactive.time_end", "22:00") or "22:00")
        now = _hhmm()
        if start <= end:
            return start <= now < end
        return now >= start or now < end

    def target_users(self) -> list[str]:
        raw = str(self._config().get("proactive.target_users", "") or "")
        return [item for item in raw.replace(",", " ").split() if item]

    def _next_sleep_seconds(self) -> float:
        """下一次检查前等多久（0.231）。

        可发时段内 → 随机 min~max 小时（保持拟人的不确定感）；
        若此刻正处在免打扰 / 时间窗外 → **睡到下一个可行时段开始**，
        而不是继续盲睡 4~8 小时（此前会一路撞在免打扰里，甚至永远轮不到可发时刻）。
        """
        low = max(1.0, self._config().float("proactive.min_interval_hours", 4.0))
        high = max(low, self._config().float("proactive.max_interval_hours", 8.0))
        base = random.uniform(low, high) * 3600
        try:
            start = str(self._config().get("proactive.time_start", "09:00") or "09:00").strip()
            end = str(self._config().get("proactive.time_end", "22:00") or "22:00").strip()
            quiet = str(self._config().get("proactive.quiet_hours", "") or "").strip()
            blocked = bool(quiet) and self._in_quiet_hours(quiet)
            if not blocked:
                now_m = _minutes_hm(_hhmm())
                s_m = _minutes_hm(start)
                e_m = _minutes_hm(end)
                if s_m <= e_m:
                    blocked = not (s_m <= now_m < e_m)
                else:  # 跨零点的时间窗
                    blocked = not (now_m >= s_m or now_m < e_m)
            if blocked:
                now_m = _minutes_hm(_hhmm())
                s_m = _minutes_hm(start)
                delta = (s_m - now_m) % (24 * 60)
                if delta > 0:
                    # 免打扰若比时间窗更晚结束，就等免打扰结束
                    if quiet:
                        q_end = quiet.split("-", 1)[1].strip() if "-" in quiet else ""
                        if q_end:
                            q_m = _minutes_hm(q_end)
                            dq = (q_m - now_m) % (24 * 60)
                            if dq > 0:
                                delta = max(delta, dq) if delta > 0 else dq
                    return min(max(60.0, delta * 60), 12 * 3600)
        except Exception:
            pass
        return base

    async def run_loop(self) -> None:
        """后台循环：启动后补检一次，之后按间隔检查；撞到不可发时段就睡到下一可行时段（0.231）。"""
        # 启动补检：此前是「先睡 4~8 小时再检查」，插件每次重载都会把这个睡眠打断，
        # 于是可能一直轮不到可发时刻（实测用户 last_sent_at 长期为 0 = 从未主动发过）。
        await asyncio.sleep(90)
        while True:
            if self.enabled():
                for user in self.target_users():
                    try:
                        await self._maybe_send(user)
                    except Exception as exc:
                        logger.warning("[Storyteller] 主动触达异常（忽略）: %s", exc)
            await asyncio.sleep(self._next_sleep_seconds())

    async def _maybe_send(self, user: str, *, force: bool = False) -> None:
        # ── 由头引擎：汇集 → 挑一条好时机的由头 ──
        engine = getattr(self._plugin, "_inspiration_engine", None)
        if engine is None:
            self._record_candidate({"user": user, "outcome": "blocked", "reason": "念头引擎未就绪"})
            return
        session_context = {"session_id": self._resolve_session(user), "user_id": user}
        bridge = self._plugin._get_memory_bridge()
        resolver = getattr(bridge, "resolve_persona_for", None)
        if callable(resolver):
            try:
                session_context["persona_id"] = await resolver(session_context)
            except Exception:
                pass
        candidates = [c for c in engine.collect(session_context=session_context) if (not c.user or c.user == user)]
        # 关系适配：好感度低 → 只允许高重要性由头
        try:
            rels = self._plugin.relationship_store.list_all()
            rel = next((r for r in rels if str(r.get("user_id") or "") == user), None)
        except Exception:
            rel = None
        aff = float((rel or {}).get("affection") or 0.35) if rel else 0.35
        max_imp = 0.5 if aff < 0.2 else (0.6 if aff < 0.4 else 0.8 if aff < 0.8 else 99.0)
        cand = engine.pick(candidates, max_importance=max_imp)
        if cand is None:
            if not force:
                self._record_candidate(
                    {"user": user, "outcome": "silent", "reason": "此刻没有自然想说的话（由头未成熟）",
                     "sources": {"candidates": len(candidates)}}
                )
                return
            # force（手动「立即尝试」）：无合适由头也要试一句——用持续源里最高重要性的素材充当由头
            fallback = max(candidates, key=lambda c: c.importance) if candidates else None
            if fallback is None:
                self._record_candidate({"user": user, "outcome": "silent", "reason": "没有任何可用素材（先让状态/日程/梦有内容）"})
                return
            cand = fallback
        # 边界通过后才进入生成
        ok, reason = self._should_send(user, bucket=daypart_bucket(), cand=cand)
        if not ok:
            self._record_candidate(
                {"user": user, "outcome": "blocked", "reason": reason,
                 "sources": {"byhead": cand.text[:80], "importance": cand.importance}}
            )
            return
        context = await self._collect_context(user)
        context["byhead"] = cand.text
        context["byhead_source"] = cand.source
        context["byhead_importance"] = cand.importance
        # 未回应温度：随 streak 阶梯放轻语气 / 更克制
        temperature = self._temperature(user)
        context["temperature"] = temperature
        context["unanswered_streak"] = max(0, int(self._user_state_for(user).get("streak", 0) or 0))
        text = await self._generate(user, context)
        if not text or text.strip() == ":NO:":
            engine._mark_raised(user, cand.text)
            # 一次性终态：沉默（不再保留"生成中"，也不再新增第二条）
            self._record_candidate(
                {"user": user, "outcome": "silent", "reason": "裁决：不值得发/像打扰",
                 "text": "" if not text else text[:120],
                 "sources": {
                     "mood": context.get("mood") or "",
                     "activity": context.get("activity") or "",
                     "memory": context.get("memory") or "",
                     "timeline": context.get("timeline") or "",
                     "search": context.get("search") or "",
                     "dream": context.get("dream") or "",
                     "byhead": cand.text or "",
                 }}
            )
            return
        ok, send_reason = await self._send(user, text)
        # 一次性终态：成功/失败（同一条记录）
        self._record_candidate(
            {"user": user, "outcome": "sent" if ok else "send_failed",
             "reason": "已发送" if ok else (send_reason or "发送失败"),
             "text": text[:120],
             "sources": {
                 "mood": context.get("mood") or "",
                 "activity": context.get("activity") or "",
                 "memory": context.get("memory") or "",
                 "timeline": context.get("timeline") or "",
                 "search": context.get("search") or "",
                 "dream": context.get("dream") or "",
                 "byhead": cand.text or "",
             }}
        )
        if ok:
            last_sent_before = self._last_sent.get(user)
            self._last_sent[user] = _now_ts()
            self._daily_count[_today()] = self._daily_count.get(_today(), 0) + 1
            self._save_meta()  # 0.231：计数与上次发送时间落盘（重载后频控不失效）
            self._daily_per_user[user] = self._daily_per_user.get(user, 0) + 1
            engine._mark_raised(user, cand.text)
            engine._note_daypart_sent(daypart_bucket(), user)
            self._record_sent(user, text)
            # 未回应动态：上次发送后对方没回 → 连续未回应 +1、悬置计时、心情联动
            dynamic = self._advance_unanswered_state(user)
            if dynamic.get("streak", 0) > 0:
                logger.info(
                    "[Storyteller] 未回应计数: user=%s streak=%s mood_triggered=%s",
                    user, dynamic.get("streak", 0), dynamic.get("mood_triggered", False),
                )
            # 回填记忆插件时间线（role=bot）：主动消息不经主链，记忆插件记录不到，
            # 不回填则时间线缺 Bot 侧、阶段总结断档。
            notifier = getattr(self._plugin, "_note_proactive_sent", None)
            if callable(notifier):
                try:
                    notifier(user, text)
                except Exception:
                    pass
            logger.info("[Storyteller] 主动消息已发送: user=%s byhead=%s text=%s", user, cand.source, text[:60])
        else:
            # 发送失败不消耗由头（下轮重试同由头）
            logger.warning("[Storyteller] 主动消息发送失败: user=%s reason=%s", user, send_reason)

    def _should_send(self, user: str, *, bucket: str = "day", cand: Any = None) -> tuple[bool, str]:
        # 静默闸门（优先于每日上限）：道理同「一个人被晾着晾了太久，自然就不再往上凑」
        silenced = self._silence_blocked(user)
        if silenced:
            return False, silenced
        # 每日上限（0 = 不限制）
        max_daily = max(0, self._config().int("proactive.max_daily", 3))
        if max_daily > 0 and self._daily_count.get(_today(), 0) >= max_daily:
            return False, f"今日已达上限 {max_daily} 条"
        # 免打扰时段
        quiet = str(self._config().get("proactive.quiet_hours", "23:00-08:30") or "").strip()
        if quiet and self._in_quiet_hours(quiet):
            return False, f"免打扰时段（{quiet}）不打扰"
        # 刚聊完顺延
        cooldown = max(0, self._config().int("proactive.cooldown_after_chat_minutes", 30))
        last_chat = self._last_interaction.get(user)
        if last_chat and _now_ts() - last_chat < cooldown * 60:
            return False, f"刚聊完 {cooldown} 分钟内不打扰"
        # 0.231：显式的「最短间隔」门。此前最短间隔只靠 run_loop 的睡眠隐式保证，
        # 一旦有别的入口（启动补检 / 面板手动触发 / 重载后重排）就会绕过它。
        min_iv = max(0.0, self._config().float("proactive.min_interval_hours", 4.0))
        last_sent_any = self._last_sent.get(user) or 0
        if min_iv > 0 and last_sent_any and _now_ts() - last_sent_any < min_iv * 3600:
            left = min_iv * 3600 - (_now_ts() - last_sent_any)
            return False, f"距上次主动还不到最短间隔 {min_iv:g} 小时（还需约 {left / 60:.0f} 分钟）"
        # 未回应降速：连续未回应越多，间隔拉得越长（像人一样，被晾着就少凑上去）
        st = self._user_state_for(user)
        streak = max(0, int(st.get("streak", 0) or 0))
        last_sent = self._last_sent.get(user)
        if last_sent:
            last_reply = self._last_interaction.get(user) or 0
            if last_reply < last_sent:
                mult = self._unanswered_interval_multiplier(streak)
                high = max(2.0, self._config().float("proactive.max_interval_hours", 8.0)) * mult
                if _now_ts() - last_sent < high * 3600:
                    note = f"上次主动后对方未回应（连续 {streak} 次），间隔已放长到 {mult:.2f} 倍等待"
                    return False, note
        return True, ""

    @staticmethod
    def _in_quiet_hours(quiet: str) -> bool:
        """当前时刻是否在免打扰时段内（HH:MM-HH:MM，支持跨零点）。"""
        try:
            now = _hhmm()
            parts = quiet.split("-")
            if len(parts) != 2:
                return False
            sm, em = _minutes_hm(parts[0]), _minutes_hm(parts[1])
            nm = _minutes_hm(now)
            if sm <= em:
                return sm <= nm < em
            return nm >= sm or nm < em
        except Exception:
            return False

    async def _collect_context(self, user: str) -> dict[str, str]:
        presence = self._plugin.presence_store.load()
        schedule = self._plugin.schedule_store.load()
        from .schedule import current_activity

        activity = current_activity(schedule, _hhmm())
        memory_hint = ""
        timeline_hint = ""
        bridge = self._plugin._get_memory_bridge() if hasattr(self._plugin, "_get_memory_bridge") else None
        if bridge is not None:
            session_context = {"session_id": self._resolve_session(user), "scope": "private", "user_id": user}
            resolver = getattr(bridge, "resolve_persona_for", None)
            if callable(resolver):
                try:
                    session_context["persona_id"] = await resolver(session_context)
                except Exception:
                    pass
            try:
                lister = getattr(bridge, "list_recent_memories", None)
                if callable(lister):
                    records = lister(session_context=session_context, limit=5)
                    if isinstance(records, list) and records:
                        items = []
                        for r in records[:5]:
                            if isinstance(r, dict):
                                content = str(r.get("content") or r.get("summary") or "")[:80]
                                if content:
                                    items.append(content)
                        memory_hint = "；".join(items)
            except Exception:
                memory_hint = ""
            try:
                tl = getattr(bridge, "get_timeline", None)
                if callable(tl):
                    events = tl(session_context=session_context, limit=5)
                    if isinstance(events, list) and events:
                        from .timeline_filter import is_llm_context_event

                        items = []
                        for e in events[:5]:
                            if not is_llm_context_event(e):
                                continue
                            if isinstance(e, dict):
                                content = str(e.get("content") or "").strip()
                                if content:
                                    items.append(content[:60])
                        timeline_hint = "；".join(items)
            except Exception:
                timeline_hint = ""
        search_note = ""
        if self._plugin.config.bool("search.enabled", False):
            try:
                from .mind import search_and_think

                result = await search_and_think(self._plugin, "最近有什么新鲜事")
                search_note = str(result.get("note") or "")[:200]
                if search_note and hasattr(self._plugin, "mind_store"):
                    self._plugin.mind_store.add_sighting(search_note)
            except Exception:
                search_note = ""
        dream_hint = ""
        dream_aftermath = ""
        try:
            store = getattr(self._plugin, "mind_store", None)
            if store is not None:
                dreams = store.all().get("dreams") or []
                if dreams:
                    dream_hint = str(dreams[0].get("text") or "")[:200]
                dream_aftermath = str(store.meta_get("dream_aftermath", "") or "")
        except Exception:
            pass
        return {
            "time": time.strftime("%Y-%m-%d %H:%M", time.localtime()),
            "mood": str(presence.get("mood") or ""),
            "energy": str(presence.get("energy") or ""),
            "activity": activity,
            "memory": memory_hint,
            "timeline": timeline_hint,
            "search": search_note,
            "dream": dream_hint,
            "dream_aftermath": dream_aftermath,
            "user": user,
        }

    async def _generate(self, user: str, context: dict[str, str]) -> str:
        try:
            from .models import chat_text, resolve_chat_provider

            provider, provider_id = resolve_chat_provider(self._plugin.context, self._plugin.config, "proactive")
            if provider is None:
                return ""
            prompt = self._build_prompt(context)
            # 主动消息：关闭思考（快）+ 限预算 300 字内
            resp = await chat_text(
                provider,
                self._plugin.config,
                prompt=prompt,
                session_id=f"storyteller_proactive:{user}",
                _max_tokens=400,
            )
            self._plugin._record_usage(resp, "proactive", provider_id or "default")
            text = str(getattr(resp, "completion_text", "") or "").strip()
            if not text or len(text) > 300:
                return ""
            if text.startswith(("（", "【", "[")):
                return ""
            return text
        except Exception as exc:
            logger.warning("[Storyteller] 主动消息生成失败: %s", exc)
            return ""

    def _build_prompt(self, context: dict[str, str]) -> str:
        """两级裁决合一：先判「值不值得说」，值得才组织自然表达。

        支持用户模板（proactive.template）：留空用内置默认；占位符：
        {由头} {心情} {日程} {记忆} {未完成} {见闻} {梦} {时间}
        """
        # 素材字典（占位符替换用）
        byhead = str(context.get("byhead") or "")
        mood = str(context.get("mood") or "")
        activity = str(context.get("activity") or "")
        memory = str(context.get("memory") or "")
        timeline = str(context.get("timeline") or "")
        search = str(context.get("search") or "")
        dream = str(context.get("dream") or "")
        time_now = str(context.get("time") or "")
        vals = {
            "{由头}": f"★ 你心里想说的由头：{byhead}（来源：{context.get('byhead_source', '')}）" if byhead else "",
            "{心情}": f"你的心情：{mood}" if mood else "",
            "{日程}": f"你此刻正在：{activity}" if activity else "",
            "{记忆}": f"你记得的约定/愿望：{memory}" if memory else "",
            "{未完成}": f"你们最近聊到：{timeline}" if timeline else "",
            "{见闻}": f"你刚看到的见闻：{search}" if search else "",
            "{梦}": f"你昨晚做了个梦：{dream}" if dream else "",
            "{时间}": f"当前时间：{time_now}" if time_now else "",
        }
        user_tpl = str(self._config().get("proactive.template", "") or "").strip()
        if user_tpl:
            text = user_tpl
            for k, v in vals.items():
                text = text.replace(k, v)
            return text
        # 内置默认（两级裁决：先判值不值得 → 值得就自然表达）
        lines = [
            "你现在可能想主动给一个在乎的人发一句消息。",
            "先看有没有「由头」：",
            "· 由头是重要的（约定、未完成的事、做过梦、惦记的事）→ 基本就该说，说出那句自然的话；",
            "· 由头很淡（只是心情/无聊）→ 想清楚了再说；",
            "只有这几种情况才判 :NO: ：对方明确在忙或刚聊过、深夜该睡了、由头真的不值一提、对方连续没回应明显不想聊。",
            "愿意说就只输出这句消息本身，不要任何解释、引号或动作描写；",
            "不要空泛的「在吗」「想你了」，也不要说「我是主动发的」这类机制话术。",
            # 0.212：两条实测出来的约束——
            # ① 长度：主动开场白原来普遍 30~50 字（见闻/梦那类还会更长），不像"随手发一条"；
            # ② 别复述：见闻类由头是新闻摘要（90+ 字），模型会原样播报标题，看着像新闻联播。
            "像随手发出去的一条消息：一两句、十几二十字就够，别写成一段话；",
            "由头只是「你为什么想起对方」，别把由头的内容原样复述出来"
            "（比如看到新闻，说「刚看到条新闻有点闹心」就够了，不用把标题念一遍）。",
        ]
        lines.append(vals["{时间}"] if vals["{时间}"] else "")
        if vals["{由头}"]:
            lines.append(vals["{由头}"])
            imp = float(context.get("byhead_importance") or 0)
            if imp >= 0.5:
                lines.append("（这个由头够重要——值得主动说，别犹豫。）")
        for v in (vals["{心情}"], vals["{日程}"], vals["{记忆}"], vals["{未完成}"], vals["{见闻}"], vals["{梦}"]):
            if v:
                lines.append(v)
        am = str(context.get("dream_aftermath") or "")
        if dream:
            if am == "nightmare":
                lines.append("那是场噩梦，你醒来后心里还留着点不安——想跟对方说说的念头更强。")
            elif am == "sweet":
                lines.append("那是场甜梦，你醒来后心里还留着点暖意。")
        # 未回应动态：连续没被理睬时放轻语气、更克制（阶梯度）
        streak = int(context.get("unanswered_streak") or 0)
        if streak >= 3:
            lines.append("你们之间最近连着几条消息都是你发、对方没回——退一步，留空间；除非这个由头真的非说不可，否则 :NO:。")
        elif streak == 2:
            lines.append("对方有一阵没回应了——低压，别连问；没什么要紧的就 :NO:。")
        elif streak == 1:
            lines.append("对方还没接话——放轻一点，别催别追问；把话说软一些。")
        lines.append("克制一点，但别把「想说话」也当成打扰。")
        return "\n".join([l for l in lines if l])

    async def _send(self, user: str, text: str) -> tuple[bool, str]:
        """发送主动消息。返回 (是否成功, 失败原因)。

        0.176：发送失败时给出「已连接平台」诊断；若配置的平台前缀不在已连接平台中、
        且 AstrBot 恰好只有一个平台可用，自动回退用该平台重试一次（多发/错发风险为零）。
        """
        try:
            from astrbot.api.event import MessageChain

            context = self._plugin.context
            session = self._resolve_session(user)
            if not session:
                return False, "无法解析目标会话（检查目标用户 QQ 号/平台前缀）"
            sender = getattr(context, "send_message", None)
            if not callable(sender):
                return False, "当前消息平台未提供发送接口（适配器未接入）"
            try:
                ok = await sender(session, MessageChain().message(text))
            except Exception as exc:
                logger.warning("[Storyteller] 主动消息发送异常: session=%s err=%s", session, exc)
                return False, f"发送异常：{str(exc)[:80] or type(exc).__name__}"
            if not ok:
                # 0.176：诊断 + 单平台自动回退（覆盖「配置前缀与实际适配器 ID 不一致」的场景）
                retry, reason = await self._retry_with_connected_platform(user, text)
                if retry:
                    return True, ""
                return False, reason
            return True, ""
        except Exception as exc:
            logger.warning("[Storyteller] 主动消息发送失败: %s", exc)
            return False, f"发送异常：{str(exc)[:80] or type(exc).__name__}"

    def _connected_platforms(self) -> list[dict[str, str]]:
        """枚举 AstrBot 当前已连接（已配置）的平台适配器 [{"id","name"}]（只读，零副作用）。"""
        try:
            manager = getattr(self._plugin.context, "platform_manager", None)
            insts = getattr(manager, "platform_insts", None) or []
            out: list[dict[str, str]] = []
            for platform in insts:
                try:
                    meta = platform.meta()
                    pid = str(getattr(meta, "id", "") or "").strip()
                    pname = str(getattr(meta, "name", "") or "").strip()
                except Exception:
                    continue
                if pid:
                    out.append({"id": pid, "name": pname})
            return out
        except Exception:
            return []

    async def _retry_with_connected_platform(self, user: str, text: str) -> tuple[bool, str]:
        """发送失败后的平台诊断与单平台回退。返回 (是否已回退成功, 诊断信息)。"""
        from astrbot.api.event import MessageChain

        context = self._plugin.context
        platforms = self._connected_platforms()
        if not platforms:
            return False, "发送接口返回失败（未检测到已连接平台/适配器未接入）"
        ids = [p["id"] for p in platforms]
        configured = str(self._config().get("proactive.session_platform", "aiocqhttp") or "aiocqhttp").strip()
        session = self._resolve_session(user)
        cur_platform = session.split(":", 1)[0] if session else configured
        # 0.236：文案说人话——「阡墨（适配器 aiocqhttp）」比原来的「阡墨（aiocqhttp）」明确得多，
        # 并讲清这里要填的是**平台标识**（会话前缀用的就是它），不是适配器类型。
        summary = "、".join(
            f"{p['id']}（适配器 {p.get('name') or '未知'}）" for p in platforms
        )
        if cur_platform in ids:
            return False, f"发送接口返回失败（目标会话平台 '{cur_platform}' 已连接，但发送未成功：适配器未连接/目标不可达？）"
        # 自动回退候选：① 只有一个平台（唯一适配器，回退回不到别处）
        #               ② 配置值其实是**适配器类型**且该类型只有一个实例（如填了 aiocqhttp，而只有一个 aiocqhttp 实例）
        alt = ""
        if len(platforms) == 1:
            alt = platforms[0]["id"]
        else:
            same_name = [p["id"] for p in platforms if str(p.get("name") or "") == cur_platform]
            if len(same_name) == 1:
                alt = same_name[0]
        if alt:
            alt_session = f"{alt}:FriendMessage:{user.split(':')[-1].strip().lstrip('@')}"
            logger.warning(
                "[Storyteller] 主动发送前缀 %s 未匹配已连接平台 %s，自动回退用 %s 尝试一次",
                configured, ids, alt,
            )
            try:
                sender = getattr(context, "send_message", None)
                if callable(sender):
                    ok = await sender(alt_session, MessageChain().message(text))
                    if ok:
                        logger.info("[Storyteller] 主动消息已用平台 %s 发送（原配置 %s 已自动回退）", alt, configured)
                        return True, ""
                    return False, (
                        f"发送接口返回失败（已回退用 {alt} 仍失败；已连接平台: {summary}）"
                    )
            except Exception as exc:
                logger.warning("[Storyteller] 回退平台发送异常: %s", exc)
        known_names = {str(p.get("name") or "") for p in platforms}
        extra = ""
        if cur_platform in known_names:
            extra = (f"「{cur_platform}」是适配器**类型**，不是平台标识；")
        return False, (
            f"发送接口返回失败：平台前缀 '{cur_platform}' 未匹配已连接平台。"
            f"{extra}「消息平台前缀」要填**平台标识**（会话前缀用的就是它，即括号前那个）：{summary}。"
            f"请在「主动」页的下拉里选一个（已连接 {len(platforms)} 个平台，无法自动判断选哪个）。"
        )

    def _resolve_session(self, user: str) -> str:
        """把目标用户解析为 unified_msg_origin 会话（0.150：容忍用户填带平台前缀/空格的用户 ID）。

        形如 "qq:123456" / "123456" / "aiocqhttp:123456" 都归一化为
        "{platform}:FriendMessage:{number}"；已是完整会话（含 Message）则原样返回。
        0.176：Message 节样式大小写归一（FriendMessage/friendmessage 均接受），
        并剥离 "message:" / "msg:" 等最外层包装前缀（部分来源会带）。
        """
        original = str(user or "").strip()
        low = original
        if ":" in original:
            # 剥离最外层包装前缀（message:/msg:…），保留核心 UMO 段
            head = original.split(":", 1)[0].strip().lower()
            if head in ("message", "msg", "chat", "session"):
                low = original.split(":", 1)[1]
            # 已是完整 UMO（含 Message 节）：大小写归一后原样返回
            if re.search(r"(?i)(friend|group|other)message", low):
                return re.sub(
                    r"(?i)(friend|group|other)message",
                    lambda m: m.group(1).capitalize() + "Message",
                    low,
                )
        platform = str(self._config().get("proactive.session_platform", "aiocqhttp") or "aiocqhttp").strip()
        if not platform:
            platform = "aiocqhttp"
        # 剥离已带的前缀（qq: / aiocqhttp: / 平台名:）只留数字段
        number = low.split(":")[-1].strip().lstrip("@")
        if not number:
            return ""
        return f"{platform}:FriendMessage:{number}"

    def note_interaction(self, event: Any) -> None:
        """记录用户互动（刚聊完顺延 / 未回应降速 / 静默闸门解除 / 心情回升）。

        0.155：命令消息（/reset、/help 等）不算「聊过」——不触发刚聊完顺延、
        不算回应、不清未回应计数（否则用户只发个 /reset 就被顺延 30 分钟）。
        """
        sender = extract_sender(event)
        user_id = sender.get("user_id") or ""
        if not user_id:
            return
        if self._event_is_command(event):
            return
        self._last_interaction[user_id] = _now_ts()
        st = self._user_state_for(user_id)
        was_awaiting = int(st.get("streak", 0) or 0) > 0
        was_linked = bool(st.get("mood_linked"))
        st["streak"] = 0
        st["awaiting_since"] = 0.0
        st["last_reply_at"] = _now_ts()
        st["last_sent_at"] = float(st.get("last_sent_at", 0) or 0)
        st["mood_linked"] = False
        self._save_user_state()
        if was_awaiting or was_linked:
            # 对方回来了：解除沉默、心情回升（若开启了联动且之前降过）
            if was_linked:
                replier = getattr(self._plugin, "_note_proactive_replied", None)
                if callable(replier):
                    try:
                        replier(user_id)
                    except Exception:
                        pass
            logger.info("[Storyteller] 主动未回应状态已归位: user=%s（此前悬置过）", user_id)

    def _event_is_command(self, event: Any) -> bool:
        """命令消息判定（复用防抖的判定逻辑；命令=系统操作，不算对话互动）。"""
        try:
            deb = getattr(self._plugin, "debounce", None)
            if deb is None or not callable(getattr(deb, "_looks_command", None)):
                return False
            text = str(getattr(event, "message_str", "") or "")
            msg_obj = getattr(event, "message_obj", None)
            raw = ""
            try:
                raw = deb._raw_text(event, msg_obj)
            except Exception:
                raw = ""
            return deb._looks_command(text) or deb._looks_command(raw)
        except Exception:
            return False

    def start(self) -> None:
        if self._loop_task is None:
            self._loop_task = asyncio.ensure_future(self.run_loop())

    async def stop(self) -> None:
        if self._loop_task is not None:
            self._loop_task.cancel()
            self._loop_task = None
