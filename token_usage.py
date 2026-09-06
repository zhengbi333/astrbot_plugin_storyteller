"""Token 记账：陪伴插件自己的调用 + 主链（AstrBot）调用分来源统计。

设计要点（独立实现，不与外部插件雷同）：
- 每次 LLM 调用后记一笔（来源 + 任务 + 模型 + 输入/输出 token + 调用次数）；
- 提供方返回了真实 usage 时优先用真实值；不返回时按文本估算（中文≈1字/1token，
  其余字符≈4字符/1token——估算口径借鉴示例插件思路但规则独立实现）；
- 来源（source）三条线：companion=陪伴插件自己、main=AstrBot 主链、memory=记忆插件
  （记忆插件由对方的记账模块持有，本模块只约定同构 stats 接口）；
- 持久化到数据目录 token.json，按日期聚合，滚动保留最近 90 天；
- 命中一条 recent 明细（最近 200 笔），供页面分页展示。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_TOKEN_FILE = "token.json"
_RETAIN_DAYS = 90
_RECENT_LIMIT = 200
_SAVE_INTERVAL = 3.0  # 记账写盘节流（秒），避免高频调用频繁全量写文件


def estimate_tokens(text: str | Any) -> int:
    """按文本字符估算 token 数（不调 LLM、零依赖）。

    规则：CJK 字符（汉字 + 中日韩标点）每字约 1 token；其余字符（拉丁/数字/符号等）
    约 4 字符 1 token。估算只用于提供方没返回 usage 时的兜底，误差可接受。
    """
    raw = str(text or "")
    if not raw:
        return 0
    cjk = 0
    for ch in raw:
        code = ord(ch)
        if 0x4E00 <= code <= 0x9FFF or 0x3000 <= code <= 0x303F:
            cjk += 1
    others = max(0, len(raw) - cjk)
    return max(0, cjk + int(others / 4.0 + 0.5))


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def _month() -> str:
    return time.strftime("%Y-%m", time.localtime())


def _now_clock() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


_SOURCE_DEFAULT = "companion"


class TokenStore:
    """token 用量记账与统计（多来源）。

    磁盘结构：
    {
      "daily": {
        "2026-08-26": {
          "total": {"input": int, "output": int, "calls": int},   # 全来源合计
          "by_source": {"companion": {"input", "output", "calls"}, ...},
          "by_task": {"companion:接管改换": {...}, "main:主链对话": {...}},
          "by_model": {"companion:deepseek-v4": {...}}
        }
      },
      "recent": [ {"time", "source", "task", "model", "input", "output"} ... ]
    }
    旧版（无来源维度）数据的 by_task 键没有 ":" 前缀，统计时按 companion 兼容处理。
    """

    def __init__(self, data_dir: Path):
        self._file = Path(data_dir) / _TOKEN_FILE
        self._data: dict[str, Any] = self._load()
        self._last_save = 0.0

    def _load(self) -> dict[str, Any]:
        try:
            if self._file.exists():
                raw = json.loads(self._file.read_text(encoding="utf-8-sig"))
                if isinstance(raw, dict) and isinstance(raw.get("daily"), dict):
                    return raw
        except Exception:
            pass
        return {"daily": {}}

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._last_save = time.monotonic()
        except Exception:
            pass

    def _maybe_save(self) -> None:
        """节流写盘：距上次保存超过阈值才写（高频记账不每笔都写文件）。"""
        if time.monotonic() - self._last_save >= _SAVE_INTERVAL:
            self._save()

    def record(
        self,
        *,
        source: str = _SOURCE_DEFAULT,
        task: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """记一笔（按来源 + 任务 + 模型累积）。"""
        inp = max(0, int(input_tokens or 0))
        out = max(0, int(output_tokens or 0))
        if inp == 0 and out == 0:
            return
        source = str(source or _SOURCE_DEFAULT).strip() or _SOURCE_DEFAULT
        day = _today()
        daily = self._data.setdefault("daily", {})
        day_data = daily.setdefault(day, {"total": {}, "by_source": {}, "by_task": {}, "by_model": {}})
        # 旧版结构迁移（升级当天）：当天还没有 by_source.companion 但顶层 total 有值，
        # 先把旧用量继承进 by_source（旧数据全部归属陪伴插件自己），避免后续统计丢量
        by_source = day_data.setdefault("by_source", {})
        if "companion" not in by_source:
            old_total = day_data.get("total", {}) or {}
            if int(old_total.get("input", 0) or 0) or int(old_total.get("output", 0) or 0):
                by_source["companion"] = {
                    "input": int(old_total.get("input", 0) or 0),
                    "output": int(old_total.get("output", 0) or 0),
                    "calls": 0,
                }
        total = day_data.setdefault("total", {})
        total["input"] = int(total.get("input", 0) or 0) + inp
        total["output"] = int(total.get("output", 0) or 0) + out
        total["calls"] = int(total.get("calls", 0) or 0) + 1
        src = day_data.setdefault("by_source", {}).setdefault(source, {"input": 0, "output": 0, "calls": 0})
        src["input"] = int(src.get("input", 0) or 0) + inp
        src["output"] = int(src.get("output", 0) or 0) + out
        src["calls"] = int(src.get("calls", 0) or 0) + 1
        task_key = f"{source}:{task}"
        task_data = day_data.setdefault("by_task", {}).setdefault(task_key, {"input": 0, "output": 0, "calls": 0})
        task_data["input"] = int(task_data.get("input", 0) or 0) + inp
        task_data["output"] = int(task_data.get("output", 0) or 0) + out
        task_data["calls"] = int(task_data.get("calls", 0) or 0) + 1
        model_key = f"{source}:{model or 'default'}"
        model_data = day_data.setdefault("by_model", {}).setdefault(model_key, {"input": 0, "output": 0})
        model_data["input"] = int(model_data.get("input", 0) or 0) + inp
        model_data["output"] = int(model_data.get("output", 0) or 0) + out
        # 最近明细（新在前）
        recent = self._data.setdefault("recent", [])
        recent.insert(0, {
            "time": _now_clock(),
            "source": source,
            "task": str(task or "")[:40],
            "model": str(model or "default")[:80],
            "input": inp,
            "output": out,
        })
        del recent[_RECENT_LIMIT:]
        # 滚动清理
        keys = sorted(daily.keys())
        if len(keys) > _RETAIN_DAYS:
            for old in keys[: len(keys) - _RETAIN_DAYS]:
                daily.pop(old, None)
        self._maybe_save()

    @staticmethod
    def _split_key(key: str) -> tuple[str, str]:
        """复合键 source:task 拆分；无冒号视为旧版 companion 数据。"""
        if ":" in str(key or ""):
            source, _, part = str(key).partition(":")
            return source, part
        return _SOURCE_DEFAULT, str(key or "")

    def _agg(self, days: list[str], key: str, source: str | None) -> list[dict[str, Any]]:
        buckets: dict[tuple[str, str], dict[str, int | str]] = {}
        for day in days:
            day_data = self._data.get("daily", {}).get(day) or {}
            section = day_data.get(key, {}) or {}
            for name, v in section.items():
                if not isinstance(v, dict):
                    continue
                item_source, part = self._split_key(name)
                if source and item_source != source:
                    continue
                b = buckets.setdefault((item_source, part), {"input": 0, "output": 0, "calls": 0})
                b["input"] = int(b["input"] or 0) + int(v.get("input", 0) or 0)
                b["output"] = int(b["output"] or 0) + int(v.get("output", 0) or 0)
                b["calls"] = int(b["calls"] or 0) + int(v.get("calls", 0) or 0)
        result = [
            {
                "source": item_source,
                "name": part,
                "input": b["input"],
                "output": b["output"],
                "calls": b["calls"],
                "total": int(b["input"] or 0) + int(b["output"] or 0),
            }
            for (item_source, part), b in buckets.items()
        ]
        result.sort(key=lambda x: -x["total"])
        return result

    def _totals(self, days: list[str], source: str | None) -> dict[str, int]:
        """按来源汇总入/出/次数。

        兼容旧版（0.124 及以前）数据：无 by_source 维度、顶层 total 直接归属
        陪伴插件自己——指定 companion 时该日回退用顶层 total（旧数据无次数）。
        """
        inp = out = calls = 0
        daily = self._data.get("daily", {})
        for day in days:
            day_data = daily.get(day) or {}
            total = day_data.get("total", {}) or {}
            src = None
            if source:
                src = (day_data.get("by_source", {}) or {}).get(source) or {}
            if src:
                inp += int(src.get("input", 0) or 0)
                out += int(src.get("output", 0) or 0)
                calls += int(src.get("calls", 0) or 0)
            elif source == _SOURCE_DEFAULT and (int(total.get("input", 0) or 0) or int(total.get("output", 0) or 0)):
                # 旧版数据：顶层 total 视为「为你续写的故事」自己的用量
                inp += int(total.get("input", 0) or 0)
                out += int(total.get("output", 0) or 0)
            elif not source:
                inp += int(total.get("input", 0) or 0)
                out += int(total.get("output", 0) or 0)
                calls += int(total.get("calls", 0) or 0)
        return {"input": inp, "output": out, "calls": calls}

    def stats(self, source: str | None = None) -> dict[str, Any]:
        """返回统计：总 / 当天 / 当月 / 每任务 / 每模型 / 最近调用。

        source=None 时为全来源合计；指定 source 时只统计该来源（任务/模型/calls
        均按来源过滤，recent 也按来源过滤）。
        """
        daily = self._data.get("daily", {})
        today = _today()
        month = _month()
        month_days = [d for d in daily if d.startswith(month)]
        all_days = list(daily.keys())
        recent_all = [r for r in self._data.get("recent", []) if isinstance(r, dict)]
        if source:
            recent_list = [r for r in recent_all if str(r.get("source", "")) == source]
        else:
            recent_list = recent_all

        def pack(t: dict[str, int]) -> dict[str, Any]:
            return {"input": t["input"], "output": t["output"], "sum": t["input"] + t["output"], "calls": t["calls"]}

        return {
            "total": pack(self._totals(all_days, source)),
            "today": pack(self._totals([today], source)),
            "month": pack(self._totals(month_days, source)),
            "by_task": self._agg(month_days, "by_task", source),
            "by_model": self._agg(month_days, "by_model", source),
            "recent": recent_list[:_RECENT_LIMIT],
        }

    def flush(self) -> None:
        """立即写盘（供停止/关闭时调用）。"""
        self._save()