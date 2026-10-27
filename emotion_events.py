"""情绪事件：被骂一句该有波动，而不是等十几分钟慢慢漂。

两段式判定（先快后准）：
1. **关键词秒判**（零延迟、不花钱）：命中"滚/傻逼/闭嘴/讨厌你"就立刻判成负向事件，
   命中"喜欢你/好可爱/真好"就判成正向；覆盖日常绝大多数情况。
2. **LLM 兜底**（可选、有日上限）：关键词没命中但句子带情绪色彩（讽刺、撒娇、冷淡）时，
   再花一次便宜调用判一次。判不出来就**不动情绪**，绝不报错中断回复。

设计原则：
- 情绪是"被事件推动"的，不是"随时间漂移"的；时间只负责慢慢回归中性。
- 幅度宁可小也不要夸张：一次被骂不该让她崩溃一整晚。
- 任何失败都降级为"无事件"。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

MAX_TEXT_CHARS = 500
DEFAULT_DAILY_LIMIT = 200

# 事件类型 → (tone, tempo, battery) 增量。负值是"低落/放慢/耗电"。
EVENT_DELTAS: dict[str, tuple[float, float, float]] = {
    "被骂": (-0.38, 0.10, -0.06),
    "被嫌弃": (-0.22, 0.06, -0.04),
    "被冷落": (-0.12, -0.06, -0.02),
    "被夸": (0.28, 0.10, 0.05),
    "被表白": (0.34, 0.14, 0.04),
    "被撒娇": (0.20, 0.06, 0.03),
    "被关心": (0.16, 0.02, 0.06),
    "吵架": (-0.44, 0.20, -0.10),
    "普通": (0.0, 0.0, 0.0),
}

# 关键词表：命中即判。顺序有意义（越激烈的越前）。
KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("吵架", ("滚", "闭嘴", "别烦我", "去死", "废物", "垃圾", "恶心", "烦死")),
    ("被骂", ("傻逼", "笨蛋", "蠢", "讨厌你", "不喜欢你", "难听", "冷血", "木头", "机器人")),
    ("被嫌弃", ("太冷漠", "好冷", "僵硬", "敷衍", "没意思", "无聊")),
    ("被表白", ("喜欢你", "我爱你", "想你了", "离不开你", "心动")),
    ("被夸", ("好可爱", "真可爱", "好棒", "真棒", "厉害", "好看", "聪明", "温柔")),
    ("被撒娇", ("抱抱", "亲亲", "陪我", "要抱", "撒娇", "嘛~", "嘛～", "嘛")),
    ("被关心", ("累不累", "早点睡", "吃饭了吗", "注意身体", "别太累", "休息")),
    ("被冷落", ("算了", "没事", "随便", "哦", "知道了")),
]

_LLM_PROMPT = """判断这句话属于哪类事件，并给情绪影响。

句子：{text}

类型只能选一个：吵架 / 被骂 / 被嫌弃 / 被冷落 / 被夸 / 被表白 / 被撒娇 / 被关心 / 普通
强度 0~1（0.2 轻微，0.6 明显，1.0 强烈）

只输出 JSON，不要解释：
{{"event": "类型", "intensity": 0.0}}"""


class EmotionError(Exception):
    """情绪判定失败（内部用，外部一律降级为无事件）。"""


@dataclass(slots=True)
class Verdict:
    event: str = "普通"
    intensity: float = 0.0
    source: str = "none"  # keyword / llm / none
    tone: float = 0.0
    tempo: float = 0.0
    battery: float = 0.0
    note: str = ""

    @property
    def is_event(self) -> bool:
        return self.event != "普通" and self.intensity > 0

    def describe(self) -> str:
        if not self.is_event:
            return "无事件"
        return f"{self.event}（强度 {self.intensity:.1f}，来源 {self.source}）"


@dataclass
class CallBudget:
    daily_limit: int = DEFAULT_DAILY_LIMIT
    counts: dict[str, int] = field(default_factory=dict)

    def _today(self) -> str:
        return time.strftime("%Y-%m-%d", time.localtime())

    def left(self) -> int:
        return max(0, self.daily_limit - int(self.counts.get(self._today(), 0)))

    def take(self) -> bool:
        day = self._today()
        if self.left() <= 0:
            return False
        self.counts[day] = int(self.counts.get(day, 0)) + 1
        return True


def match_keywords(text: str) -> tuple[str, float]:
    """关键词秒判。返回 (事件, 强度)，没命中返回 ("普通", 0)。"""
    body = str(text or "").strip()
    if not body:
        return "普通", 0.0
    for event, words in KEYWORDS:
        for word in words:
            if word and word in body:
                # 越激烈的类型给越高强度
                base = {"吵架": 0.95, "被骂": 0.8, "被嫌弃": 0.6, "被表白": 0.85,
                        "被夸": 0.6, "被撒娇": 0.55, "被关心": 0.5, "被冷落": 0.3}.get(event, 0.5)
                # 强烈标点再加一点
                if re.search(r"[!！]{2,}|[?？]{2,}", body):
                    base = min(1.0, base + 0.1)
                return event, base
    return "普通", 0.0


def scale(event: str, intensity: float) -> tuple[float, float, float]:
    """把 (事件, 强度) 换成三维增量。"""
    delta = EVENT_DELTAS.get(event, (0.0, 0.0, 0.0))
    k = max(0.0, min(1.0, float(intensity)))
    return (round(delta[0] * k, 4), round(delta[1] * k, 4), round(delta[2] * k, 4))


def _parse_llm(raw: str) -> tuple[str, float]:
    text = str(raw or "").strip()
    match = re.search(r"\{[^{}]*\}", text, re.S)
    if not match:
        raise EmotionError("模型没给 JSON")
    try:
        data = json.loads(match.group(0))
    except ValueError as exc:
        raise EmotionError(f"JSON 解析失败：{exc}") from exc
    event = str(data.get("event") or "普通").strip()
    if event not in EVENT_DELTAS:
        event = "普通"
    try:
        intensity = float(data.get("intensity") or 0.0)
    except (TypeError, ValueError):
        intensity = 0.0
    return event, max(0.0, min(1.0, intensity))


def judge_keywords_only(text: str) -> Verdict:
    """只跑关键词（同步、零延迟）。"""
    event, intensity = match_keywords(text)
    if event == "普通":
        return Verdict()
    tone, tempo, battery = scale(event, intensity)
    return Verdict(event=event, intensity=intensity, source="keyword",
                   tone=tone, tempo=tempo, battery=battery)


async def judge_with_llm(
    provider: Any, text: str, *, budget: CallBudget | None = None,
) -> Verdict:
    """LLM 兜底判定。任何异常都返回"无事件"，绝不抛给调用方。"""
    body = str(text or "").strip()[:MAX_TEXT_CHARS]
    if not body or provider is None:
        return Verdict()
    if budget is not None and not budget.take():
        return Verdict(note="今日判定额度已用完")
    prompt = _LLM_PROMPT.format(text=body)
    try:
        resp = await provider.text_chat(prompt=prompt)
        raw = str(getattr(resp, "completion_text", "") or "")
        if not raw:
            raw = str(getattr(resp, "result", "") or "")
        event, intensity = _parse_llm(raw)
    except Exception as exc:
        return Verdict(note=f"判定失败（已忽略）：{type(exc).__name__}")
    if event == "普通" or intensity <= 0.05:
        return Verdict(source="llm")
    tone, tempo, battery = scale(event, intensity)
    return Verdict(event=event, intensity=intensity, source="llm",
                   tone=tone, tempo=tempo, battery=battery)


async def judge(
    provider: Any, text: str, *, budget: CallBudget | None = None, use_llm: bool = True,
) -> Verdict:
    """先关键词，没命中再用 LLM（可关）。"""
    quick = judge_keywords_only(text)
    if quick.is_event or not use_llm:
        return quick
    return await judge_with_llm(provider, text, budget=budget)


def apply_to_presence(presence: dict[str, Any], verdict: Verdict) -> dict[str, Any]:
    """把增量写进 presence（就地修改并返回）。幅度夹在合理区间。"""
    if not verdict.is_event:
        return presence
    for key, delta in (("tone", verdict.tone), ("tempo", verdict.tempo), ("battery", verdict.battery)):
        try:
            current = float(presence.get(key) or 0.0)
        except (TypeError, ValueError):
            current = 0.0
        low, high = (-1.0, 1.0) if key != "battery" else (0.0, 1.0)
        presence[key] = round(max(low, min(high, current + delta)), 4)
    presence["last_event"] = verdict.event
    presence["last_event_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    return presence
