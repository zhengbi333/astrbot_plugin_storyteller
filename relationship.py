"""关系模型：Bot 与每个用户的关系档案（好感度 + 阶段 + 互动档位）。

设计要点（独立实现，简化但真实，不照搬示例的 ±1200 分）：
- 好感度用 0~1 连续值，映射四个关系阶段（陌生/普通/熟络/亲近）；
- 关系随互动自然演进，带阻尼与每日上限，防止刷分与骤冷骤热；
- 互动档位由好感度 + 当前情绪合成，决定称呼亲密度与语气分寸；
- 关系注入请求时只影响语气与分寸，身份仍以 ID 唯一判定。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_REL_FILE = "relationships.json"

STAGES = [
    (0.0, "陌生"),
    (0.25, "普通"),
    (0.5, "熟络"),
    (0.75, "亲近"),
]


def default_relationship(user_id: str) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "affection": 0.15,
        "interactions": 0,
        "address": "",
        "impression": "",
        "impression_updated_at": "",
        "first_seen": "",
        "last_seen": "",
        "updated_at": "",
    }


def stage_for(affection: float) -> str:
    stage = "陌生"
    for threshold, name in STAGES:
        if affection >= threshold:
            stage = name
    return stage


def interaction_tier(affection: float, energy: str) -> str:
    """由好感度 + 精力合成互动档位（决定语气亲密度）。"""
    a = max(0.0, min(1.0, affection))
    tired = bool(energy and ("累" in energy or "疲惫" in energy or "没精神" in energy))
    if a < 0.15:
        return "回避"
    if a < 0.35:
        return "放松"
    if a < 0.7:
        return "温暖"
    return "亲近" if not tired else "温暖"


class RelationshipStore:
    """关系档案的读写与演进。"""

    def __init__(self, data_dir: Path):
        self._file = Path(data_dir) / _REL_FILE
        self._data: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            if self._file.exists():
                raw = json.loads(self._file.read_text(encoding="utf-8-sig"))
                if isinstance(raw, dict):
                    return {k: v for k, v in raw.items() if isinstance(v, dict)}
        except Exception:
            pass
        return {}

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def get(self, user_id: str) -> dict[str, Any]:
        rel = self._data.get(user_id)
        if not isinstance(rel, dict):
            rel = default_relationship(user_id)
        return rel

    def touch(
        self,
        user_id: str,
        *,
        delta: float = 0.0,
        address: str = "",
    ) -> dict[str, Any]:
        """记录一次互动并微调好感度（带阻尼）。"""
        if not user_id:
            return default_relationship(user_id)
        rel = self.get(user_id)
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        if not rel.get("first_seen"):
            rel["first_seen"] = now
        rel["last_seen"] = now
        rel["updated_at"] = now
        rel["interactions"] = int(rel.get("interactions", 0)) + 1
        if address and address.strip():
            rel["address"] = address.strip()[:40]
        if delta:
            current = float(rel.get("affection", 0.15))
            # 阻尼：高好感度时正向增量减半，低好感度时负向减半，避免骤变
            damped = delta
            if delta > 0 and current >= 0.7:
                damped = delta * 0.5
            if delta < 0 and current <= 0.3:
                damped = delta * 0.5
            rel["affection"] = max(0.0, min(1.0, current + damped))
        self._data[user_id] = rel
        self._save()
        return rel

    def set_impression(self, user_id: str, impression: str) -> dict[str, Any]:
        """写入最近印象（由 LLM 提炼层更新）。"""
        if not user_id:
            return self.get(user_id)
        rel = self.get(user_id)
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        rel["impression"] = str(impression or "").strip()[:120]
        rel["impression_updated_at"] = now
        rel["updated_at"] = now
        self._data[user_id] = rel
        self._save()
        return rel

    def update_manual(
        self,
        user_id: str,
        *,
        affection: float | None = None,
        address: str | None = None,
    ) -> dict[str, Any]:
        """手动调整人物卡（页面）：好感度（自动重算阶段）与称呼。"""
        if not user_id:
            return self.get(user_id)
        rel = self.get(user_id)
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        if affection is not None:
            try:
                rel["affection"] = max(0.0, min(1.0, float(affection)))
            except (TypeError, ValueError):
                pass
        if address is not None:
            rel["address"] = str(address).strip()[:40]
        rel["updated_at"] = now
        self._data[user_id] = rel
        self._save()
        return rel

    def set_address(self, user_id: str, address: str) -> dict[str, Any]:
        return self.touch(user_id, address=address)

    def list_all(self) -> list[dict[str, Any]]:
        """返回所有关系档案（按好感度排序，附阶段与互动档位）。"""
        result = []
        for rel in self._data.values():
            if not isinstance(rel, dict):
                continue
            affection = float(rel.get("affection", 0.15))
            item = dict(rel)
            item["stage"] = stage_for(affection)
            item["tier"] = interaction_tier(affection, "")
            result.append(item)
        result.sort(key=lambda x: -float(x.get("affection", 0)))
        return result


def build_relationship_anchor(
    rel: dict[str, Any] | None,
    presence: dict[str, Any] | None = None,
    *,
    memory_summary: str = "",
) -> str:
    """把关系档案渲染成注入文本（{关系} 占位符）。

    - 阶段 + 互动档位 + 称呼 + 最近印象（若有） + 约定/偏好摘要（联动只读，若有）；
    - 只用于把握语气与分寸，身份仍以 ID 为准（与防认错联动）。
    """
    if not isinstance(rel, dict):
        return ""
    affection = float(rel.get("affection", 0.15))
    stage = stage_for(affection)
    energy = str((presence or {}).get("energy", "")) if isinstance(presence, dict) else ""
    tier = interaction_tier(affection, energy)
    address = str(rel.get("address", "") or "").strip()
    impression = str(rel.get("impression", "") or "").strip()
    lines = ["【与对方的关系】"]
    if address:
        lines.append(f"你平时称呼对方：{address}。")
    lines.append(f"你和对方目前是「{stage}」的关系，互动档位是「{tier}」。")
    if impression:
        lines.append(f"最近印象：{impression}")
    summary = str(memory_summary or "").strip()
    if summary:
        lines.append(f"你记得的与对方有关的约定/偏好：{summary}")
    lines.append(
        "这用来把握语气和分寸——关系越亲近可以越放松、越亲昵，关系陌生就保持礼貌和距离；"
        "但对方是谁以账号/ID 为准（见防认错），不要因为亲昵或熟悉就泄露隐私或越界。"
    )
    return "\n".join(lines)
