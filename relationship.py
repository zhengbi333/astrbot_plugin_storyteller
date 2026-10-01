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

# 0.193：久未互动的自然降温（可在「关系」页配置）
REL_DECAY_DEFAULTS = {
    "enabled": True,
    "free_days": 3.0,   # 3 天内不降温（日常忙碌不惩罚）
    "per_day": 0.01,    # 超过免降温期后，每天回落多少好感度
    "min": 0.15,        # 降温下限（不会低于这个值，保留基本温度）
}

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
    """关系档案的读写与演进（含 0.193 久未互动自然降温）。"""

    def __init__(self, data_dir: Path, config: Any = None):
        self._file = Path(data_dir) / _REL_FILE
        self._config = config
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
        # 0.193：读取即结算久未互动的自然降温（变化才落盘）
        if self._settle(rel):
            self._data[user_id] = rel
            self._save()
        return rel

    # ---------------------------------------------------------- 自然降温（0.193）

    def _decay_policy(self) -> dict[str, Any]:
        """读降温策略（配置热更新；无配置时用默认值）。"""
        cfg = self._config
        if cfg is None:
            return dict(REL_DECAY_DEFAULTS)
        try:
            return {
                "enabled": bool(cfg.bool("relationship.decay_enabled", True)),
                "free_days": max(0.0, float(cfg.int("relationship.decay_free_days", 3) or 0)),
                "per_day": max(0.0, float(cfg.float("relationship.decay_per_day", 0.01))),
                "min": max(0.0, min(1.0, float(cfg.float("relationship.decay_min", 0.15)))),
            }
        except Exception:
            return dict(REL_DECAY_DEFAULTS)

    @staticmethod
    def _parse_ts(value: Any) -> float:
        try:
            return time.mktime(time.strptime(str(value or "")[:19], "%Y-%m-%d %H:%M:%S"))
        except Exception:
            return 0.0

    def _settle(self, rel: dict[str, Any], *, force: bool = False) -> bool:
        """按「上次接触」结算自然降温，返回好感度是否变化。

        锚点 = 上次接触时的好感度（affection_anchor / affection_anchor_at）：
        免降温期内不回落；超过后按 overdue 天数 × 每天幅度回落，且有下限。
        节流：同一档案 1 小时内不重复结算（force=True 绕过，互动时用）。
        """
        policy = self._decay_policy()
        if not policy["enabled"]:
            return False
        now = time.time()
        last_settle = self._parse_ts(rel.get("decay_settled_at", ""))
        if not force and last_settle and now - last_settle < 3600:
            return False
        anchor_at = (
            self._parse_ts(rel.get("affection_anchor_at", ""))
            or self._parse_ts(rel.get("last_seen", ""))
            or self._parse_ts(rel.get("updated_at", ""))
            or now
        )
        anchor_raw = rel.get("affection_anchor")
        try:
            anchor_val = float(anchor_raw) if anchor_raw is not None else float(rel.get("affection", 0.15))
        except Exception:
            anchor_val = float(rel.get("affection", 0.15))
        days = max(0.0, (now - anchor_at) / 86400.0)
        overdue = days - float(policy["free_days"])
        target = anchor_val if overdue <= 0 else max(float(policy["min"]), anchor_val - overdue * float(policy["per_day"]))
        try:
            current = float(rel.get("affection", 0.15))
        except Exception:
            current = 0.15
        changed = False
        if target < current - 1e-6:
            rel["affection"] = max(0.0, min(1.0, target))
            changed = True
        # 锚点保持（未接触就不动基准），补记结算时间
        rel["affection_anchor"] = anchor_val
        if not rel.get("affection_anchor_at"):
            rel["affection_anchor_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(anchor_at))
        rel["decay_settled_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        return changed

    def touch(
        self,
        user_id: str,
        *,
        delta: float = 0.0,
        address: str = "",
    ) -> dict[str, Any]:
        """记录一次互动并微调好感度（带阻尼；接触即刷新降温锚点）。"""
        if not user_id:
            return default_relationship(user_id)
        rel = self.get(user_id)
        self._settle(rel, force=True)  # 互动前先结算此前的自然降温
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
        # 接触即重置降温基准：从现在的好感度与现在的时间重新起算
        rel["affection_anchor"] = float(rel.get("affection", 0.15))
        rel["affection_anchor_at"] = now
        rel["decay_settled_at"] = now
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
        # 手动调整即视为一次接触：重置降温基准（否则刚调高就被算作逾期回落）
        rel["affection_anchor"] = float(rel.get("affection", 0.15))
        rel["affection_anchor_at"] = now
        rel["decay_settled_at"] = now
        self._data[user_id] = rel
        self._save()
        return rel

    def set_address(self, user_id: str, address: str) -> dict[str, Any]:
        return self.touch(user_id, address=address)

    def list_all(self) -> list[dict[str, Any]]:
        """返回所有关系档案（按好感度排序，附阶段、互动档位与「多久没聊」）。"""
        result = []
        changed = False
        for rel in self._data.values():
            if not isinstance(rel, dict):
                continue
            if self._settle(rel):
                changed = True
            affection = float(rel.get("affection", 0.15))
            item = dict(rel)
            item["stage"] = stage_for(affection)
            item["tier"] = interaction_tier(affection, "")
            last = self._parse_ts(rel.get("last_seen", "")) or self._parse_ts(rel.get("updated_at", ""))
            item["idle_days"] = round(max(0.0, (time.time() - last) / 86400.0), 1) if last else None
            result.append(item)
        if changed:
            self._save()
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
