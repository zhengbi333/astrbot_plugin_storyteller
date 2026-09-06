"""念头引擎：主动对话的「由头」生命周期管理。

独立于示例插件的实现思路：这里不搞候选池+优先级队列，而是维护
「由头（inspiration）」——主动想去说一件事的来源 + 时效窗口 + 状态。
由头经「值得说吗 → 怎么自然说」两级裁决后进入克制日志。

设计取向（非雷同）：
- 由头 = {源, 文本, 重要性(0~1), 时效窗口(起止), 状态, 目标用户}，
  用「好时机（窗内）+ 时段配额 + 新鲜度」来决定何时提，而不是脉冲队列；
- 持续源（状态/日程/记忆/未完话题/见闻/梦）由本模块周期归纳；
- 事件源（早晚安/三餐/约定后续/生日）按时间与记忆触发；
- 登记接口：其它模块 register_inspiration_source() 注入"可主动提的事"
  （为未来能力留缝，无外部注册时零成本）。
"""

from __future__ import annotations

import time
from typing import Any, Callable

from .log import logger

_DAY_SECONDS = 3600


def _now() -> float:
    return time.time()


def _hhmm() -> str:
    return time.strftime("%H:%M", time.localtime())


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def _minutes(hhmm: str) -> int:
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 0


# 时段桶：早晨/白天/傍晚/深夜（与示例的 daypart 名称不同，自持定义）
DAYPARTS = [
    ("morning", (6 * 60, 11 * 60 + 59), "早晨"),
    ("day", (12 * 60, 17 * 60 + 59), "白天"),
    ("evening", (18 * 60, 22 * 60 + 59), "傍晚"),
    ("night", (23 * 60, 5 * 60 + 59), "深夜"),
]


def daypart_bucket(now_minutes: int | None = None) -> str:
    m = _minutes(_hhmm()) if now_minutes is None else now_minutes
    # 深夜桶跨零点（23:00~05:59），单独判定：其它三段为普通小区间
    if m >= 23 * 60 or m < 6 * 60:
        return "night"
    for key, (lo, hi), _label in DAYPARTS:
        if key != "night" and lo <= m <= hi:
            return key
    return "day"


def daypart_label(key: str) -> str:
    for k, _lo, label in DAYPARTS:
        if k == key:
            return label
    return key


def default_daypart_caps() -> dict[str, int]:
    """默认每时段主动上限（深夜 0，避免半夜打扰）。"""
    return {"morning": 1, "day": 2, "evening": 1, "night": 0}


class Inspiration:
    """一条由头：来源、内容、重要性与时效窗口、状态。"""

    def __init__(
        self,
        source: str,
        text: str,
        *,
        importance: float = 0.5,
        window_start: float | None = None,
        window_end: float | None = None,
        user: str = "",
        can_delay: bool = True,
    ):
        self.source = source
        self.text = str(text or "")[:300]
        self.importance = max(0.0, min(1.0, float(importance)))
        self.window_start = window_start
        self.window_end = window_end
        self.user = user
        self.can_delay = can_delay
        self.state = "brewing"  # brewing 酝酿 | ready 可提 | raised 已提 | sleeping 沉睡
        self.created_at = _now()

    def in_window(self, now: float | None = None) -> bool:
        t = _now() if now is None else now
        if self.window_start and t < self.window_start:
            return False
        if self.window_end and t > self.window_end:
            return False
        return True

    def expired(self, now: float | None = None) -> bool:
        t = _now() if now is None else now
        return bool(self.window_end and t > self.window_end)


class InspirationEngine:
    """由头引擎：汇集持续/事件/登记由头 → 挑"好时机"的一条 → 交给裁决。

    克制原则（宁可不说）：由头很少且机会不好时返回空；不追求"凑数"。
    """

    def __init__(self, plugin: Any):
        self._plugin = plugin
        self._registered: dict[str, Callable[[Any], list[dict[str, Any]]]] = {}
        self._meta: dict[str, Any] = {"used_pairs": {}, "daypart_sent": {}}

    # ---- 登记接口（为未来模块留缝） ----
    def register_source(self, name: str, provider: Callable[[Any], list[dict[str, Any]]]) -> None:
        self._registered[name] = provider

    def registered_sources(self) -> list[str]:
        return list(self._registered.keys())

    def _persist_key(self, user: str, text: str) -> str:
        return f"{user}::{text[:60]}"

    def _mark_raised(self, user: str, text: str) -> None:
        day = _today()
        self._meta.setdefault("used_pairs", {}).setdefault(day, {})
        self._meta["used_pairs"][day][self._persist_key(user, text)] = _now()

    def already_raised_today(self, user: str, text: str) -> bool:
        day = _today()
        return self._persist_key(user, text) in (self._meta.get("used_pairs") or {}).get(day, {})

    def _note_daypart_sent(self, bucket: str, user: str) -> None:
        day = _today()
        self._meta.setdefault("daypart_sent", {}).setdefault(day, {})
        part = self._meta["daypart_sent"][day].setdefault(bucket, {})
        part[user] = part.get(user, 0) + 1

    def daypart_sent_count(self, bucket: str, user: str) -> int:
        day = _today()
        return ((self._meta.get("daypart_sent") or {}).get(day, {}).get(bucket, {}) or {}).get(user, 0)

    # ---- 汇集由头 ----
    def collect(self) -> list[Inspiration]:
        """全部今日由头（持续源 + 事件源 + 登记源）。"""
        out: list[Inspiration] = []
        try:
            out.extend(self._from_persistent())
        except Exception as exc:
            logger.warning("[Storyteller] 由头-持续源失败: %s", exc)
        try:
            out.extend(self._from_events())
        except Exception as exc:
            logger.warning("[Storyteller] 由头-事件源失败: %s", exc)
        try:
            for name, provider in self._registered.items():
                try:
                    for raw in provider(self._plugin) or []:
                        if not isinstance(raw, dict):
                            continue
                        text = str(raw.get("text") or "").strip()
                        if not text:
                            continue
                        out.append(
                            Inspiration(
                                name,
                                text,
                                importance=float(raw.get("importance") or 0.5),
                                window_start=raw.get("window_start"),
                                window_end=raw.get("window_end"),
                                user=str(raw.get("user") or ""),
                                can_delay=bool(raw.get("can_delay", True)),
                            )
                        )
                except Exception:
                    continue
        except Exception:
            pass
        # 未被提及过的、且今天没提过的保留；已提的进入 sleeping
        for ins in out:
            if self.already_raised_today(ins.user, ins.text):
                ins.state = "sleeping"
            elif ins.in_window():
                ins.state = "ready"
            else:
                ins.state = "brewing"
        return out

    def _from_persistent(self) -> list[Inspiration]:
        """持续源：状态/日程/记忆/未完话题/见闻/梦。"""
        plugin = self._plugin
        out: list[Inspiration] = []
        # 状态
        try:
            presence = plugin.presence_store.load()
            mood = str(presence.get("mood") or "")
            if mood:
                out.append(Inspiration("状态", f"此刻的心情是：{mood[:80]}", importance=0.35))
        except Exception:
            pass
        # 日程
        try:
            from .schedule import current_activity

            activity = current_activity(plugin.schedule_store.load(), _hhmm())
            if activity:
                out.append(Inspiration("日程", f"此刻正在：{activity[:80]}", importance=0.4))
        except Exception:
            pass
        # 约定/愿望（记忆）：只取「约定/承诺」类最近记忆，无则跳过
        # （不混入偏好/身份等其它记忆，避免把无关记忆错当成"说好的事"）
        try:
            getter = getattr(plugin, "_recent_promise_hint", None)
            mem = getter(limit=4) if callable(getter) else ""
            if mem:
                out.append(Inspiration("记忆", f"还记得约好的事：{mem[:120]}", importance=0.5))
        except Exception:
            pass
        # 见闻 / 梦
        try:
            mind = plugin.mind_store.all()
            s = (mind.get("sightings") or [])
            if s:
                out.append(Inspiration("见闻", str(s[0].get("text") or "")[:120], importance=0.45))
            d = (mind.get("dreams") or [])
            if d:
                out.append(Inspiration("梦", str(d[0].get("text") or "")[:120], importance=0.55))
        except Exception:
            pass
        return out

    def _from_events(self) -> list[Inspiration]:
        """事件源：早晚安 / 三餐 / 约定后续 / 生日（按需触发，克制）。"""
        plugin = self._plugin
        out: list[Inspiration] = []
        now_min = _minutes(_hhmm())
        try:
            # 早晚安
            if 7 * 60 <= now_min <= 9 * 60:
                out.append(Inspiration("早安", "早晨醒来，想跟对方说声早上好", importance=0.4,
                                       window_start=None, window_end=None, can_delay=False))
            if 21 * 60 <= now_min <= 23 * 60:
                out.append(Inspiration("晚安", "要睡了，想跟对方道个晚安", importance=0.4,
                                       window_start=None, window_end=None, can_delay=False))
            # 三餐关怀（到点才提）
            for label, lo, hi in (("早餐", 7 * 60, 9 * 60), ("午餐", 11 * 60 + 30, 13 * 60),
                                  ("晚餐", 17 * 60 + 30, 19 * 60 + 30)):
                if lo <= now_min <= hi:
                    out.append(Inspiration("三餐", f"到{label}时间了，想问问对方吃了没", importance=0.35,
                                           window_start=None, window_end=None, can_delay=False))
        except Exception:
            pass
        # 约定后续：只取「约定/承诺」类记忆（promise），其它记忆不得冒充约定
        try:
            getter = getattr(plugin, "_recent_promise_hint", None)
            mem = getter(limit=3) if callable(getter) else ""
            if mem:
                out.append(Inspiration("约定后续", f"之前说好/约好的事：{mem[:120]}", importance=0.6))
        except Exception:
            pass
        return out

    # ---- 挑选 ----
    def pick(self, candidates: list[Inspiration], max_importance: float = 99.0) -> Inspiration | None:
        """挑一条：窗口内、未提、重要性最高；若都不成熟返回 None。"""
        ready = [c for c in candidates if c.state == "ready" and c.importance <= max_importance]
        if not ready:
            return None
        ready.sort(key=lambda c: (-c.importance, c.created_at))
        return ready[0]
