"""日记：Bot 的每日日记——从当天的状态、梦境、见闻、互动整理。

设计要点（独立实现，不与外部插件雷同）：
- 每天深夜自动整理一篇日记（像真人睡前随手写几行）；
- 素材来自当天真实发生的：状态历史、梦境、见闻、情绪余波；
- 日记可被后续的状态演化/主动对话引用，形成「自我连续性」。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_DIARY_FILE = "diary.json"


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def build_diary_prompt(day_context: str) -> str:
    """构造「整理今日日记」的提示词。"""
    return (
        "请为这个角色写一篇简短的今日日记。只输出日记正文，不要标题、日期或解释，用简体中文书写。\n"
        "要求：自然、克制、像真人睡前随手写的几行；从今天的状态、情绪起伏、做过的事、"
        "冒出的念头、做的梦里取材，还要把「她是谁」与「最近记得的约定/重要事」自然地融进去——"
        "日记是她这个人的一天，不是流水账；可以有一点点自我对话和感慨，但不要夸张、不要总结成报告，"
        "不要出现「用户」「机器人」这类通称，用「他/她/对方」或名字。\n\n"
        f"今天的情况：\n{day_context or '（平淡的一天）'}"
    )


class DiaryStore:
    """日记的读写（存插件数据目录 diary.json）。"""

    def __init__(self, data_dir: Path):
        self._file = Path(data_dir) / _DIARY_FILE
        self._data: dict[str, Any] = {"entries": []}
        self._load()

    def _load(self) -> None:
        try:
            if self._file.exists():
                raw = json.loads(self._file.read_text(encoding="utf-8-sig"))
                if isinstance(raw, dict) and isinstance(raw.get("entries"), list):
                    self._data = raw
        except Exception:
            pass

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def entries(self) -> list[dict[str, Any]]:
        return list(self._data.get("entries", []))

    def has_today(self) -> bool:
        return any(e.get("date") == _today() for e in self._data.get("entries", []))

    def add(self, date: str, content: str) -> None:
        content = (content or "").strip()
        if not content:
            return
        entries = self._data.setdefault("entries", [])
        # 同一天覆盖写（重新整理）
        for e in entries:
            if e.get("date") == date:
                e["content"] = content[:2000]
                e["at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                self._save()
                return
        entries.insert(
            0,
            {
                "date": date,
                "content": content[:2000],
                "at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            },
        )
        if len(entries) > 60:
            entries = entries[:60]
        self._data["entries"] = entries
        self._save()
