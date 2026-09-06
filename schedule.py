"""日程锚：每日日程 + 未来规划（缓存池 1）+ 延误日程（缓存池 2）。

设计要点（独立实现，不与外部插件雷同）：
- 每天一份完整日程（时间 → 活动），带 note 与被替换来源；
- 日程可被 LLM 改写：原计划被替换时进入「延误日程」缓存池并标注原因；
- 「未来规划」缓存池存放还没排进某天的安排，下次生成日程时综合时间/上下文决定是否写入；
- 按当前时间判断此刻活动，供状态演化与主动对话使用。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_SCHEDULE_FILE = "schedule.json"


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def default_schedule() -> dict[str, Any]:
    return {
        "date": "",
        "entries": [],
        "backlog": [],
        "future": [],
    }


class ScheduleStore:
    """日程的读写与缓存池管理。"""

    def __init__(self, data_dir: Path):
        self._file = Path(data_dir) / _SCHEDULE_FILE
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        data = default_schedule()
        try:
            if self._file.exists():
                raw = json.loads(self._file.read_text(encoding="utf-8-sig"))
                if isinstance(raw, dict):
                    for key in data:
                        if key in raw:
                            data[key] = raw[key]
        except Exception:
            pass
        if not isinstance(data.get("entries"), list):
            data["entries"] = []
        if not isinstance(data.get("backlog"), list):
            data["backlog"] = []
        if not isinstance(data.get("future"), list):
            data["future"] = []
        return data

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def load(self) -> dict[str, Any]:
        """读取当前日程；日期过期则 entries 视为空（backlog/future 保留）。"""
        data = dict(self._data)
        if data.get("date") != _today():
            data["entries"] = []
        return data

    def save_entries(self, entries: Any) -> dict[str, Any]:
        normalized = self._normalize_entries(entries if isinstance(entries, list) else [])
        self._data["date"] = _today()
        self._data["entries"] = normalized
        self._save()
        return self.load()

    @staticmethod
    def _normalize_entries(items: list[Any]) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            start = str(item.get("start") or "").strip()
            activity = str(item.get("activity") or "").strip()
            if not start or not activity:
                continue
            result.append(
                {
                    "start": start[:5],
                    "end": str(item.get("end") or "").strip()[:5],
                    "activity": activity[:80],
                    "note": str(item.get("note") or "").strip()[:120],
                    "replaced_from": str(item.get("replaced_from") or "").strip()[:120],
                }
            )
            if len(result) >= 40:
                break
        result.sort(key=lambda x: x["start"])
        return result

    def replace(self, *, start: str, activity: str, note: str = "", move_original: bool = True) -> dict[str, Any]:
        """改写某时段的日程；原活动按需进入延误缓存池。"""
        data = self.load()
        entries = list(data.get("entries", []))
        replaced_from = ""
        for item in entries:
            if item.get("start") == start[:5]:
                replaced_from = item.get("activity", "")
                if move_original and replaced_from and replaced_from != activity:
                    self._data.setdefault("backlog", []).insert(
                        0,
                        {
                            "activity": replaced_from,
                            "reason": note or "被替换",
                            "at": _now(),
                        },
                    )
                break
        new_entry = {
            "start": start[:5],
            "end": "",
            "activity": activity[:80],
            "note": note[:120],
            "replaced_from": replaced_from,
        }
        entries = [e for e in entries if e.get("start") != start[:5]]
        entries.append(new_entry)
        entries.sort(key=lambda x: x["start"])
        self._data["date"] = _today()
        self._data["entries"] = entries
        self._save()
        return self.load()

    def add_future(self, *, activity: str, date: str = "", note: str = "") -> dict[str, Any]:
        """加入未来规划缓存池。"""
        if not activity or not activity.strip():
            return self.load()
        self._data.setdefault("future", []).insert(
            0,
            {"activity": activity[:80], "date": (date or "")[:10], "note": note[:120], "at": _now()},
        )
        self._save()
        return self.load()

    def consume_future(self, activity: str) -> dict[str, Any]:
        """从未来规划移除一条（写入日程时调用）。"""
        self._data["future"] = [
            f for f in self._data.get("future", []) if f.get("activity") != activity
        ]
        self._save()
        return self.load()


def current_activity(schedule: Any, now_hhmm: str) -> str:
    """按当前时间（HH:MM）判断此刻活动（兼容 dict 与旧 list 两种结构）。"""
    entries = schedule.get("entries") if isinstance(schedule, dict) else schedule
    if not isinstance(entries, list):
        return ""
    now = now_hhmm[:5]
    for item in entries:
        if not isinstance(item, dict):
            continue
        start = item.get("start", "")
        end = item.get("end", "")
        if not start:
            continue
        if end:
            if start <= end:
                if start <= now < end:
                    return item.get("activity", "")
            else:
                if now >= start or now < end:
                    return item.get("activity", "")
        else:
            if now >= start:
                return item.get("activity", "")
    return ""


def build_schedule_anchor(schedule: Any, now_hhmm: str) -> str:
    """把当前日程渲染成注入文本（仅素材，不照搬）。"""
    activity = current_activity(schedule, now_hhmm)
    if not activity:
        return ""
    return (
        "【当前日程】\n"
        f"你现在正在：{activity}。\n"
        "这只影响你的语气和节奏（比如忙碌时就简短、专注一点），"
        "不要主动提日程、科目或任务，除非对方问起；更不要把日程写成已经真实发生的事。"
    )


def build_schedule_generate_prompt(
    *,
    persona_desc: str = "",
    persona_injection: str = "",
    memories: str = "",
    weather: str = "",
    presence: str = "",
    closet: list[Any] | None = None,
    future: list[Any] | None = None,
    backlog: list[Any] | None = None,
    diary_time: str = "23:30",
    diary_minutes: int = 20,
) -> str:
    """构造「生成一天完整日程 + 穿搭」的提示词，结合人格/世界观/记忆/天气/衣柜。"""
    lines = [
        "请为这个角色生成今天一整天的完整日程和穿搭。"
        "只输出一个 JSON 对象，不要任何解释或代码块标记，字段固定为：",
        '{"entries": [{"start": "HH:MM", "end": "HH:MM", "activity": "活动", "note": "简短说明"}], '
        '"outfit": {"items": ["衣服/鞋/配饰"], "note": "今天这样穿的理由"}}',
        "要求：",
        "1. entries 覆盖完整一天 00:00~24:00，不许有空档：深夜到清晨写「睡觉」（如 23:30–07:30 深睡），"
        "随后起床、三餐、工作或学习、休息、晚间、就寝，让全天每个时段都有安排；",
        "2. 活动要具体、像真人，必须贴合下面给的人格/世界观设定与记忆，"
        "能看出她的性格与生活痕迹，不要写成通用模板；",
        "3. outfit 的 items 必须从衣柜里选 2~5 件（用衣柜里的名字），结合天气/场合/心情给一句理由；",
        "4. 整体要像这个角色真实的一天；",
        "5. 输出精简：entries 不超过 12 段，activity 一两句话讲清，note 尽量短，不要长篇；",
        f"6. 必须有一段『写日记』（大约 {diary_time} 前后，{diary_minutes} 分钟左右，睡前写写今天），"
        "activity 写「写日记」或「记日记」，note 简单说明（一天的收尾）。",
    ]
    if persona_injection:
        lines.append(f"★ 人物画像：她的人格与世界观念（日程里的每个安排都要顺着这个人会做的来）：{persona_injection.strip()}")
    if persona_desc:
        lines.append(f"★ 人物画像：她的说话性格/气质：{persona_desc.strip()}")
    if presence:
        lines.append(f"她此刻的状态：{presence}")
    if weather:
        lines.append(f"今天天气：{weather}")
    if memories:
        lines.append(f"记忆里的约定/愿望/偏好：{memories}")
    if closet:
        closet_lines = "、".join(str(c.get("name") or "") for c in closet if isinstance(c, dict))
        if closet_lines:
            lines.append(f"她的衣柜：{closet_lines}")
    if future:
        future_lines = "；".join(str(f.get("activity") or "") for f in future[:5] if isinstance(f, dict))
        if future_lines:
            lines.append(f"未来规划（时间合适就排进今天，否则保留）：{future_lines}")
    if backlog:
        backlog_lines = "；".join(str(b.get("activity") or "") for b in backlog[:5] if isinstance(b, dict))
        if backlog_lines:
            lines.append(f"之前延误的事（今天有空就补上）：{backlog_lines}")
    return "\n".join(lines)


def parse_schedule(text: str) -> dict[str, Any] | None:
    """解析 LLM 返回的日程 JSON（0.150：宽松容错 + 失败记录原始输出）。"""
    from .json_util import parse_json_lenient_logged

    value = parse_json_lenient_logged(text, "日程生成结果")
    return value if isinstance(value, dict) else None


# ---------------------------------------------------------------- 实时调整（对话中的安排）

def build_auto_plan_prompt(
    *,
    user_text: str,
    schedule: Any,
    outfit: Any,
    closet: list[Any] | None = None,
) -> str:
    """构造「对话中对方给了安排 → 像人一样决定怎么办」的决策提示词。

    输出 JSON 固定字段：
    - action: "add"（新增安排）/ "replace"（替换某时段）/ "add_future"（排不进今天就进未来规划）/
      "reschedule_backlog"（把延误的事重新排进今天）/ "dress"（对方要求改穿搭）/
      "add_closet"（对方给你买了新衣服，加进衣柜）/ "none"（不用改）
    - entry: {"start","end","activity","note"}（add/replace/reschedule_backlog 用）
    - target_start: replace 时被替换时段的开始时间
    - outfit: {"items":[...], "note": "..."}（dress 用）
    - closet_item: {"name": "衣服名", "category": "类别", "note": "备注"}（add_closet 用）
    - reason: 一句话说明怎么想的
    """
    entries = []
    if isinstance(schedule, dict):
        entries = schedule.get("entries") or []
    backlog = schedule.get("backlog") or [] if isinstance(schedule, dict) else []
    future = schedule.get("future") or [] if isinstance(schedule, dict) else []
    outfit_items = []
    if isinstance(outfit, dict):
        outfit_items = outfit.get("items") or []
    closet_names = []
    for c in (closet or []):
        if isinstance(c, dict) and c.get("name"):
            closet_names.append(str(c.get("name")))
    if not closet_names:
        closet_list = ""
    else:
        closet_list = "、".join(closet_names[:30])

    def fmt_entries(items: list[Any]) -> str:
        parts = []
        for it in items[:12] if isinstance(items, list) else []:
            if isinstance(it, dict):
                s = f"{it.get('start', '')}-{it.get('end', '')} {it.get('activity', '')}"
                if it.get("note"):
                    s += f"（{it.get('note')}）"
                if it.get("replaced_from"):
                    s += f"（原计划：{it.get('replaced_from')}）"
                parts.append(s)
        return "；".join(parts) or "（暂无）"

    def fmt_simple(items: list[Any], label: str) -> str:
        parts = []
        for it in items[:8] if isinstance(items, list) else []:
            if isinstance(it, dict):
                s = str(it.get("activity") or "")
                if it.get("date"):
                    s += f"（{it.get('date')}）"
                if it.get("reason"):
                    s += f" [原因：{it.get('reason')}]"
                parts.append(s)
        return "；".join(parts) or f"（暂无{label}）"

    return "\n".join(
        [
            "对方在对话里说了这句话：",
            f"「{user_text[:200]}」",
            "",
            "以下是这个角色现在知道的安排：",
            f"今天日程：{fmt_entries(entries)}",
            f"延误（之前没完成）：{fmt_simple(backlog, '延误')}",
            f"未来规划：{fmt_simple(future, '未来')}",
            f"当前穿着：{'、'.join(str(x) for x in outfit_items[:6]) or '（没穿具体的，或没提）'}",
            f"衣柜：{closet_list or '（暂无）'}",
            "",
            "请像真人一样决定该怎么办：",
            "1. 如果对方是在给新的明确安排（时间+要做的事），判断重要性/冲突：",
            "   - 更重要 → 替换对应时段（目标时段进「延误」），action=replace；",
            "   - 同量级/可并列 → 排进空档，action=add（有 end 就给 end，没有就只给 start）；",
            "   - 排不进今天/是以后的事 → action=add_future；",
            "   - 恰好能补上延误的事 → action=reschedule_backlog；",
            "2. 如果对方在说穿什么（换衣服/别穿某件/穿哪件/衣柜），→ action=dress，items 从现有衣柜和对方说的里选；",
            "3. 如果对方是在送/买了新衣服（新衣服/给你买了/送你的），→ action=add_closet，"
            "closet_item 给出那件衣服的名字与类别（没说的类别就合理猜一个），名字用对方说的称呼；",
            "4. 如果只是闲聊/提问/没给安排 → action=none，什么都不要改。",
            "",
            "只输出一个 JSON 对象，不要任何解释或代码块标记：",
            '{"action":"add|replace|add_future|reschedule_backlog|dress|add_closet|none",'
            ' "entry":{"start":"HH:MM","end":"HH:MM","activity":"...","note":"..."},'
            ' "target_start":"HH:MM","outfit":{"items":["..."],"note":"..."},'
            ' "closet_item":{"name":"...","category":"...","note":"..."},"reason":"一句话"}',
        ]
    )


def apply_auto_plan(decision: dict[str, Any], schedule_store: "ScheduleStore", wardrobe_store: Any) -> dict[str, Any]:
    """执行一次自动调整决策，返回 {applied, summary, action}。

    - add：插入日程（空档或直接追加一行，按 start 排序）；
    - replace：替换 target_start 时段，原活动进延误池；
    - add_future：进未来规划缓存池；
    - reschedule_backlog：从延误池取出对应活动排进今天；
    - dress：更新当前穿搭；
    - none：什么都不做。
    """
    if not isinstance(decision, dict):
        return {"applied": False, "action": "none", "summary": "无有效决策"}
    action = str(decision.get("action") or "none").strip()
    entry = decision.get("entry") if isinstance(decision.get("entry"), dict) else {}
    reason = str(decision.get("reason") or "").strip()[:120]

    if action == "add":
        start = str(entry.get("start") or "").strip()[:5]
        activity = str(entry.get("activity") or "").strip()[:80]
        if start and activity:
            data = schedule_store.load()
            data.setdefault("entries", []).append(
                {
                    "start": start,
                    "end": str(entry.get("end") or "").strip()[:5],
                    "activity": activity,
                    "note": str(entry.get("note") or "").strip()[:120],
                    "replaced_from": "",
                }
            )
            schedule_store.save_entries(data["entries"])
            return {"applied": True, "action": "add", "summary": f"新增 {start} {activity}" + (f"（{reason}）" if reason else "")}

    if action == "replace":
        target = str(decision.get("target_start") or "").strip()[:5]
        start = str(entry.get("start") or target).strip()[:5]
        activity = str(entry.get("activity") or "").strip()[:80]
        if start and activity:
            data = schedule_store.load()
            replaced_from = ""
            for item in data.get("entries", []):
                if item.get("start") == start:
                    replaced_from = item.get("activity", "")
                    if replaced_from and replaced_from != activity:
                        schedule_store._data.setdefault("backlog", []).insert(
                            0, {"activity": replaced_from, "reason": reason or "被替换", "at": _now()}
                        )
                    break
            schedule_store._data["date"] = _today()
            schedule_store._data["entries"] = [
                e
                for e in data.get("entries", [])
                if e.get("start") != start
            ] + [
                {
                    "start": start,
                    "end": str(entry.get("end") or "").strip()[:5],
                    "activity": activity,
                    "note": str(entry.get("note") or "").strip()[:120],
                    "replaced_from": replaced_from,
                }
            ]
            schedule_store._data["entries"].sort(key=lambda x: x["start"])
            schedule_store._save()
            return {"applied": True, "action": "replace", "summary": f"替换 {start} {activity}" + (f"（{reason}）" if reason else "")}

    if action == "add_future":
        activity = str(entry.get("activity") or "").strip()[:80]
        if activity:
            schedule_store.add_future(
                activity=activity,
                date=str(entry.get("end") or "").strip()[:10] or "",
                note=str(entry.get("note") or "").strip()[:120] or reason,
            )
            return {"applied": True, "action": "add_future", "summary": f"加入未来规划：{activity}" + (f"（{reason}）" if reason else "")}

    if action == "reschedule_backlog":
        data = schedule_store.load()
        matched = None
        for item in list(data.get("backlog", [])):
            if str(item.get("activity") or "")[:20] == str(entry.get("activity") or "")[:20]:
                matched = item
                break
        if matched:
            schedule_store._data["backlog"] = [
                b for b in data.get("backlog", []) if b is not matched
            ]
            start = str(entry.get("start") or "").strip()[:5]
            schedule_store._data.setdefault("entries", []).append(
                {
                    "start": start,
                    "end": str(entry.get("end") or "").strip()[:5],
                    "activity": str(matched.get("activity") or "").strip()[:80],
                    "note": str(entry.get("note") or "").strip()[:120] or str(matched.get("reason") or ""),
                    "replaced_from": "",
                }
            )
            schedule_store._data["date"] = _today()
            schedule_store._data["entries"].sort(key=lambda x: x["start"])
            schedule_store._save()
            return {"applied": True, "action": "reschedule_backlog", "summary": f"补上延误：{matched.get('activity')}"}

    if action == "dress" and wardrobe_store is not None:
        outfit = decision.get("outfit") if isinstance(decision.get("outfit"), dict) else {}
        items = [str(x).strip() for x in (outfit.get("items") or []) if str(x).strip()]
        note = str(outfit.get("note") or reason or "").strip()[:200]
        if items:
            wardrobe_store.set_outfit(items, note)
            return {"applied": True, "action": "dress", "summary": "更新穿搭：" + "、".join(items[:6])}

    if action == "add_closet" and wardrobe_store is not None:
        item = decision.get("closet_item") if isinstance(decision.get("closet_item"), dict) else {}
        name = str(item.get("name") or "").strip()[:60]
        if name and hasattr(wardrobe_store, "add_item"):
            wardrobe_store.add_item(
                name,
                str(item.get("category") or "").strip()[:40],
                str(item.get("note") or "").strip()[:120],
            )
            return {"applied": True, "action": "add_closet", "summary": f"衣柜新增：{name}"}

    return {"applied": False, "action": "none", "summary": reason or "不需要改动"}
