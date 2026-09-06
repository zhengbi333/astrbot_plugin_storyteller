"""状态锚（“这一刻的你”）：心绪三表 + 心事 + 互动涟漪 + 语气走廊。

设计要点（独立实现，不与外部插件雷同；重点是“像人”的叙事而非仪表盘）：
- 心绪用三个直觉“表”：调子 tone（低沉→轻快）/ 转速 tempo（慢→急）/ 电量 battery（亏→满）；
- 心事 drift：心里正飘着的事（≤3 件，演化浮现、随时间淡出）；
- 互动涟漪 ripple：有重量的互动留下“还没完全回过神”的余光（≤3 条，新的顶旧的，自然消散）；
- 语气走廊 stance：读取时同步合成“此刻开口的姿势”（心绪+心事+时间底色），注入 {状态} 只给语言不给数值；
- 演化用“节拍”而非每秒衰减：按节拍像人一样缓过来/淡下去；事件是“染色”一笔而非加减分；
- 时间底色（深夜/清晨/白天/赴约前）作为背景光影响语气，不是强制闸门；
- 注入只影响语气/长短/节奏/话题，不降低理解质量。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_PRESENCE_FILE = "presence.json"
_HISTORY_LIMIT = 10
# 节拍冲刷：数值朝中性小幅置回/淡出的速率（按秒，节拍粒度调用）
_DRIFT_TTL = 3600 * 2      # 心事约 2 小时淡出
_RIPPLE_TTL = 3600 * 1.5   # 涟漪约 1.5 小时消散
_ECHO_TTL = 3600 * 2       # 最近余波约 2 小时淡出
_TOWARD_NEUTRAL = 0.00010  # 三表朝中性回归（30min 节拍约 0.18 量级）

DRIFT_KINDS = ("约定回音", "未了的事", "给某人的挂念")
RIPPLE_KINDS = ("分享", "求助", "道谢", "争执", "冷落", "回应")


def _now_ts() -> float:
    return time.time()


def _parse_ts(value: Any) -> float:
    if not value:
        return 0.0
    try:
        return time.mktime(time.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return 0.0


def _fmt_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def default_presence() -> dict[str, Any]:
    return {
        "tone": 0.0, "tempo": 0.0, "battery": 0.5,
        "mood": "",
        "drift": [],          # [{text, since, kind}]  心里正飘的事
        "ripples": [],        # [{text, since, kind}]  互动涟漪（刚那话还没完全出来）
        "echoes": [],         # [{text, since, kind}]  最近余波（演化输入的"当下"素材）
        "thought": "",
        "energy_label": "",
        "updated_at": "",
        "source": "manual",
        "history": [],
    }


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _norm_three(presence: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    """兼容旧数据：新键（tone/tempo/battery）优先，旧键（valence/arousal/energy）兜底迁移。"""
    presence["tone"] = clamp(float(raw.get("tone", raw.get("valence", 0.0)) or 0.0), -1.0, 1.0)
    presence["tempo"] = clamp(float(raw.get("tempo", raw.get("arousal", 0.0)) or 0.0), -1.0, 1.0)
    presence["battery"] = clamp(float(raw.get("battery", raw.get("energy", 0.5)) or 0.5), 0.0, 1.0)
    return presence


def _norm_lists(presence: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    for key in ("drift", "ripples", "echoes"):
        items = raw.get(key) or []
        if isinstance(items, list):
            presence[key] = [it for it in items if isinstance(it, dict)][:3]
        else:
            presence[key] = []
    return presence


def apply_decay(presence: dict[str, Any]) -> dict[str, Any]:
    """旧式时间衰减（兼容旧调用方）；新逻辑用节拍冲刷 _tide。"""
    updated = _parse_ts(presence.get("updated_at"))
    if updated <= 0:
        return presence
    elapsed = max(0.0, _now_ts() - updated)
    presence["tone"] = round(presence.get("tone", 0.0) * max(0.0, 1.0 - 0.000096 * elapsed), 4)
    presence["tempo"] = round(presence.get("tempo", 0.0) * max(0.0, 1.0 - 0.000096 * elapsed), 4)
    battery = presence.get("battery", 0.5)
    presence["battery"] = round(battery + (0.5 - battery) * min(1.0, 0.000046 * elapsed), 4)
    return presence


def adjust_emotion(
    presence: dict[str, Any],
    *,
    valence_delta: float = 0.0,
    arousal_delta: float = 0.0,
    energy_delta: float = 0.0,
) -> dict[str, Any]:
    """情绪事件即时微调（旧 API 保留）；新染色建议用 stain()。"""
    presence["tone"] = clamp(presence.get("tone", 0.0) + valence_delta, -1.0, 1.0)
    presence["tempo"] = clamp(presence.get("tempo", 0.0) + arousal_delta, -1.0, 1.0)
    presence["battery"] = clamp(presence.get("battery", 0.5) + energy_delta, 0.0, 1.0)
    return presence


def stain(presence: dict[str, Any], kind: str, text: str = "") -> dict[str, Any]:
    """事件“染色”：按互动类型扰动心绪 + 留下一句涟漪。返回新的 presence（调用方保存）。"""
    kind = str(kind or "")
    if kind == "分享":
        presence = adjust_emotion(presence, valence_delta=0.05, arousal_delta=0.03)
    elif kind == "求助":
        presence = adjust_emotion(presence, energy_delta=-0.03)
    elif kind == "道谢":
        presence = adjust_emotion(presence, valence_delta=0.08, arousal_delta=-0.02)
    elif kind == "争执":
        presence = adjust_emotion(presence, valence_delta=-0.06, arousal_delta=0.06)
    elif kind == "冷落":
        # 主动消息被晾着：心里落空（主动模块未回应心情联动，含涟漪）
        presence = adjust_emotion(presence, valence_delta=-0.05, energy_delta=-0.03)
    elif kind == "回应":
        # 对方终于回话：心里松一口气（未回应状态归位时回升）
        presence = adjust_emotion(presence, valence_delta=0.05, arousal_delta=0.02)
    # 涟漪：留一条“还没完全回过神”的余光（新的顶旧的）
    if kind in RIPPLE_KINDS:
        ripples = [r for r in presence.get("ripples") or [] if isinstance(r, dict)]
        ripples.insert(
            0,
            {"text": str(text or "")[:80], "since": _fmt_now(), "kind": kind},
        )
        presence["ripples"] = ripples[:3]
    # 最近余波（演化输入的“当下”素材）：同为新的顶旧的，稍短
    echoes = [e for e in presence.get("echoes") or [] if isinstance(e, dict)]
    echoes.insert(0, {"text": str(text or "")[:60], "since": _fmt_now(), "kind": kind})
    presence["echoes"] = echoes[:3]
    return presence


def tide(presence: dict[str, Any], elapsed_seconds: float) -> dict[str, Any]:
    """节拍冲刷：像人一样缓过来/淡下去（不调 LLM）。

    - 心事与涟漪按存活时长淡出（超 TTL 移除，其余按比例减轻“分量”）；
    - 心绪三表朝中性小幅置回。
    """
    for key, ttl in (("drift", _DRIFT_TTL), ("ripples", _RIPPLE_TTL), ("echoes", _ECHO_TTL)):
        items = [it for it in presence.get(key) or [] if isinstance(it, dict)]
        kept = []
        for it in items:
            since = _parse_ts(it.get("since"))
            if since <= 0:
                kept.append(it)
                continue
            age = max(0.0, elapsed_seconds if since == 0 else max(0.0, _now_ts() - since))
            if age >= ttl:
                continue  # 淡出
            kept.append(it)
        presence[key] = kept[:3]
    presence["tone"] = round(presence.get("tone", 0.0) * max(0.0, 1.0 - _TOWARD_NEUTRAL * elapsed_seconds), 4)
    presence["tempo"] = round(presence.get("tempo", 0.0) * max(0.0, 1.0 - _TOWARD_NEUTRAL * elapsed_seconds), 4)
    battery = presence.get("battery", 0.5)
    presence["battery"] = round(battery + (0.5 - battery) * min(1.0, _TOWARD_NEUTRAL * elapsed_seconds), 4)
    return presence


def _compose_time_bg(now: str, schedule: dict[str, Any] | None) -> str:
    """时间底色（背景光）：深夜/清晨/白天/傍晚 + 赴约前（只读日程，尽力而为）。"""
    hhmm = (now or "00:00")
    try:
        hour = int(hhmm[11:13] or hhmm[:2])
    except Exception:
        hour = 0
    if 23 <= hour or hour < 5:
        base = "夜深了，不自觉地轻和缓一点"
    elif hour < 9:
        base = "刚缓过来，话还不太多"
    elif hour < 18:
        base = "普通白天的清醒感"
    else:
        base = "一天快收尾，松弛一点"
    upcoming = ""
    if isinstance(schedule, dict):
        try:
            from .schedule import current_activity

            act = current_activity(schedule, hhmm[11:16])
            if act:
                upcoming = f"；待会儿还有安排（{act[:40]}），先收着点"
        except Exception:
            upcoming = ""
    return base + upcoming


def compose_stance(presence: dict[str, Any], schedule: dict[str, Any] | None = None, now: str = "") -> str:
    """合成“语气走廊”：此刻开口的姿势（心绪 + 心事 + 时间底色）。纯同步，不调 LLM。"""
    if not isinstance(presence, dict):
        return ""
    if not now:
        now = _fmt_now()
    tone = clamp(float(presence.get("tone", 0.0)), -1.0, 1.0)
    tempo = clamp(float(presence.get("tempo", 0.0)), -1.0, 1.0)
    battery = clamp(float(presence.get("battery", 0.5)), 0.0, 1.0)

    parts: list[str] = []
    if tone > 0.25:
        parts.append("话会飘一点、明快些")
    elif tone < -0.25:
        parts.append("话会沉一些、温度低一点")
    else:
        parts.append("大体平稳")
    if tempo > 0.25:
        parts.append("回得利落一些")
    elif tempo < -0.25:
        parts.append("慢半拍，不急着应")
    if battery < 0.3:
        parts.append("有点没电，能省则省")
    elif battery > 0.75:
        parts.append("电量足，愿意多聊几句")

    stances = ["你此刻开口的姿势：" + "，".join(parts) + "。"]
    drift = [it for it in presence.get("drift") or [] if isinstance(it, dict)]
    if drift:
        first = str(drift[0].get("text") or "").strip()
        if first:
            stances.append(f"心里还挂着：{first[:60]}")
    ripples = [it for it in presence.get("ripples") or [] if isinstance(it, dict)]
    if ripples:
        first = str(ripples[0].get("text") or "").strip()
        if first:
            stances.append(f"刚才那段话还没完全出来：{first[:60]}")
    stances.append("只当作语气、长短和节奏的底色，别机械复述，也别因状态降低理解和回答质量。")
    return "\n".join(stances)


def build_presence_anchor(presence: dict[str, Any]) -> str:
    """把当前状态渲染成注入文本：语气走廊 + 一句心情（不给数值）。"""
    if not isinstance(presence, dict):
        return ""
    stance = compose_stance(presence)
    if not stance:
        return ""
    mood = str(presence.get("mood") or "").strip()
    lines = ["【此刻的状态】"]
    if mood:
        lines.insert(1, f"你现在的心情：{mood}")
    lines.append(stance)
    return "\n".join(lines)


def _history_text(history: list[Any]) -> str:
    if not isinstance(history, list) or not history:
        return ""
    lines = []
    for h in history[-4:]:
        if isinstance(h, dict):
            mood = str(h.get("mood") or "").strip()
            at = str(h.get("at") or "").strip()
            if mood:
                lines.append(f"- {at}：{mood}")
    return "\n".join(lines)


def build_presence_generate_prompt(
    *,
    now: str,
    schedule: str,
    memories: str = "",
    context: str = "",
    previous: dict[str, Any] | None = None,
    weather: str = "",
    time_bg: str = "",
    echoes: str = "",
    memory_material: str = "",
) -> str:
    """构造「按当前处境演化状态」的提示词（输入只用「当下」：时间/时间底色/日程/天气/最近余波/最近对话/上次状态）。

    memories/memory_material 只作可选的「心事素材」，不驱动情绪；长期记忆不是情绪来源。
    """
    parts = [
        "请为「我」生成此刻的情绪状态。只输出一个 JSON 对象，不要任何解释或代码块标记，字段固定为：",
        '{"tone": 调子(-1到1，负低沉正轻快), "tempo": 转速(-1到1，负慢正急), "battery": 电量(0到1，0亏1满), '
        '"mood": "心情的一句话", "drift": ["心里正飘着的事(最多2条，没有就空数组)"]}',
        "说明：这三表像人的直觉——话是沉是飘、回得快慢、还有没有劲；不是学术评分。",
    ]
    infos: list[str] = []
    if now:
        infos.append(f"当前时间：{now}")
    if time_bg:
        infos.append(f"时间底色：{time_bg}")
    if weather:
        infos.append(f"当前天气：{weather}")
    if schedule:
        infos.append(f"当前日程：{schedule}")
    if echoes:
        infos.append(f"刚发生不久的事（最近余波）：{echoes}")
    if context:
        infos.append(f"最近对话与对方情绪：{context}")
    if memory_material:
        infos.append(f"（可选心事素材，仅当真的还惦记才用）：{memory_material}")
    if previous and isinstance(previous, dict):
        prev_line = (
            f"当前维度：调子 {previous.get('tone', 0):.2f} / 转速 {previous.get('tempo', 0):.2f} / 电量 {previous.get('battery', 0.5):.2f}"
        )
        hist = _history_text(previous.get("history"))
        drift = "；".join(
            str(it.get("text") or "") for it in (previous.get("drift") or []) if isinstance(it, dict)
        )
        ripple = "；".join(
            str(it.get("text") or "") for it in (previous.get("ripples") or []) if isinstance(it, dict)
        )
        if drift:
            prev_line += "\n心里挂着：" + drift
        if ripple:
            prev_line += "\n还留着的余光：" + ripple
        if hist:
            prev_line += "\n" + hist
        infos.append(prev_line)
    if infos:
        parts.append("\n".join(infos))
    parts.append(
        "要求："
        "1. 基于当前维度自然演化——情绪有连续性，不要毫无缘由地突然大变；"
        "2. 单次变化克制（一般不超过 0.3），除非发生明显事件；"
        "3. 深夜/忙碌会拉低电量；对方的情绪会影响你，但不必完全同步；"
        "4. 实时情绪只该由「当下处境 + 刚发生的余波 + 上次状态的延续」决定，"
        "   不要被长期的旧记忆牵着走（旧约定只在确实还惦记时才可作为心事，且只影响“心里挂着”而不是情绪本身）；"
        "5. drift 只在“确实还惦记着什么”时填（约定的回音、未了的事、给某人的挂念），没有就空；"
        "6. mood 一句话、drift 每条简短，不要太夸张、不要机翻腔。"
    )
    return "\n".join(parts)


def parse_presence(text: str) -> dict[str, Any] | None:
    """解析 LLM 返回的状态 JSON（0.150：宽松容错）。"""
    if not text:
        return None
    from .json_util import parse_json_lenient

    return parse_json_lenient(text)


class PresenceStore:
    """状态档案的读写（存插件数据目录 presence.json）。"""

    def __init__(self, data_dir: Path):
        self._file = Path(data_dir) / _PRESENCE_FILE

    def load(self, *, with_decay: bool = True) -> dict[str, Any]:
        presence = default_presence()
        try:
            if self._file.exists():
                raw = json.loads(self._file.read_text(encoding="utf-8-sig"))
                if isinstance(raw, dict):
                    for key in presence:
                        if key in raw:
                            presence[key] = raw[key]
        except Exception:
            pass
        presence = _norm_three(presence, presence)
        presence = _norm_lists(presence, presence)
        if with_decay and presence.get("updated_at"):
            presence = tide(presence, max(0.0, _now_ts() - _parse_ts(presence.get("updated_at"))))
        if not isinstance(presence.get("history"), list):
            presence["history"] = []
        return presence

    def save(self, presence: dict[str, Any]) -> dict[str, Any]:
        loaded = self.load(with_decay=False)
        normalized = default_presence()
        if isinstance(presence, dict):
            normalized["tone"] = clamp(float(presence.get("tone", 0.0) or 0.0), -1.0, 1.0)
            normalized["tempo"] = clamp(float(presence.get("tempo", 0.0) or 0.0), -1.0, 1.0)
            normalized["battery"] = clamp(float(presence.get("battery", 0.5) or 0.5), 0.0, 1.0)
            for key in ("mood", "thought", "energy_label", "updated_at", "source"):
                if key in presence:
                    normalized[key] = str(presence[key] or "").strip()[:400]
            drift = presence.get("drift") or []
            if isinstance(drift, list):
                normalized["drift"] = [it for it in drift if isinstance(it, dict)][:3]
            # 涟漪与最近余波：传入则用，缺失则保留既有（避免演化清空事件产物）
            for key in ("ripples", "echoes"):
                items = presence.get(key)
                if isinstance(items, list):
                    normalized[key] = [it for it in items if isinstance(it, dict)][:3]
                else:
                    normalized[key] = loaded.get(key) or []
        history = loaded.get("history") or []
        snapshot = {
            "tone": normalized["tone"], "tempo": normalized["tempo"], "battery": normalized["battery"],
            "mood": normalized["mood"], "at": normalized["updated_at"],
        }
        if snapshot["mood"] or abs(snapshot["tone"]) > 0.02:
            if not history or (
                abs(history[-1].get("tone", 0.0) - snapshot["tone"]) > 0.05
                or history[-1].get("mood") != snapshot["mood"]
            ):
                history.append(snapshot)
                if len(history) > _HISTORY_LIMIT:
                    history = history[-_HISTORY_LIMIT:]
        normalized["history"] = history
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(
                json.dumps(normalized, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
        return normalized
