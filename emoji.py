"""表情包：本地图库 + 自定义分类 + 语境匹配渲染。

设计要点（独立实现，不与外部插件雷同）：
- 表情包存本地目录（emojis/<分类ID>/），分类标题与描述可自定义；
- 渲染阶段把回复文本里的 [EMOJI:分类标题] 占位符替换成真实表情包；
- 每次按分类随机选一张，命中分类即表达对应情绪。
"""

from __future__ import annotations

import json
import random
import re
import time
import uuid
from pathlib import Path
from typing import Any

EMOJI_PATTERN = re.compile(r"\[EMOJI:([^\]]+)\]")
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


class EmojiStore:
    """表情包图库管理 + 发送策略（去重 / 反馈权重 / 用户可关）。"""

    def __init__(self, data_dir: Path):
        self._dir = Path(data_dir) / "emojis"
        self._meta_file = Path(data_dir) / "emoji_categories.json"
        self._prefs_file = Path(data_dir) / "emoji_prefs.json"

    # ------------------------------------------------------------ 元数据

    def _load_meta(self) -> list[dict[str, Any]]:
        try:
            if self._meta_file.exists():
                raw = json.loads(self._meta_file.read_text(encoding="utf-8-sig"))
                if isinstance(raw, list):
                    return [m for m in raw if isinstance(m, dict)]
        except Exception:
            pass
        return []

    def _save_meta(self, meta: list[dict[str, Any]]) -> None:
        try:
            self._meta_file.parent.mkdir(parents=True, exist_ok=True)
            self._meta_file.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def categories(self) -> list[dict[str, Any]]:
        result = []
        for m in self._load_meta():
            cid = str(m.get("id") or "")
            result.append(
                {
                    "id": cid,
                    "title": str(m.get("title") or cid),
                    "description": str(m.get("description") or ""),
                    "count": len(self._files(cid)),
                }
            )
        return result

    def add_category(self, title: str, description: str = "") -> dict[str, Any]:
        title = (title or "").strip()
        if not title:
            raise ValueError("分类标题不能为空")
        meta = self._load_meta()
        if any(str(m.get("title") or "") == title for m in meta):
            raise ValueError("分类标题已存在")
        cid = uuid.uuid4().hex[:8]
        meta.append({"id": cid, "title": title, "description": (description or "").strip()})
        self._save_meta(meta)
        return {"id": cid, "title": title, "description": (description or "").strip(), "count": 0}

    def update_category(self, cid: str, title: str, description: str) -> dict[str, Any]:
        meta = self._load_meta()
        for m in meta:
            if str(m.get("id") or "") == cid:
                if title and title.strip():
                    m["title"] = title.strip()
                m["description"] = (description or "").strip()
                self._save_meta(meta)
                return {"id": cid, "title": m["title"], "description": m["description"]}
        raise ValueError("分类不存在")

    def remove_category(self, cid: str) -> None:
        meta = self._load_meta()
        meta = [m for m in meta if str(m.get("id") or "") != cid]
        self._save_meta(meta)
        try:
            directory = self._dir / cid
            if directory.exists():
                for p in directory.iterdir():
                    try:
                        if p.is_file():
                            p.unlink()
                    except Exception:
                        pass
                try:
                    directory.rmdir()
                except Exception:
                    pass
        except Exception:
            pass

    def _files(self, cid: str) -> list[str]:
        directory = self._dir / cid
        if not directory.exists():
            return []
        return sorted(
            p.name for p in directory.iterdir() if p.suffix.lower() in _IMAGE_EXTS
        )

    def files_with_preview(self, cid: str, limit: int = 8) -> list[dict[str, str]]:
        """0.180：返回分类内图片的预览（原图 data URL，前端 <img> 直接可显示）。

        动图取原图（<img> 自动播放）；超过 limit 张只取前 limit（附 total 由调用方判断）。
        """
        import base64
        import mimetypes

        names = self._files(cid)[: max(1, min(30, int(limit)))]
        out: list[dict[str, str]] = []
        for name in names:
            path = self._dir / cid / name
            if not path.exists():
                continue
            try:
                data = path.read_bytes()
                if len(data) > 2 * 1024 * 1024:
                    continue  # 超过 2MB 不给预览（避免页面卡顿），保留文件可删
                mime = mimetypes.guess_type(name)[0] or "image/png"
                out.append({"name": name, "data_url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"})
            except Exception:
                continue
        return out

    def add_emoji(self, cid: str, filename: str, content: bytes) -> dict[str, Any]:
        directory = self._dir / cid
        directory.mkdir(parents=True, exist_ok=True)
        ext = Path(filename).suffix.lower()
        if ext not in _IMAGE_EXTS:
            raise ValueError("不支持的图片格式")
        target = directory / f"{uuid.uuid4().hex[:8]}{ext}"
        target.write_bytes(content)
        return {"file": target.name, "count": len(self._files(cid))}

    def remove_emoji(self, cid: str, filename: str) -> None:
        target = self._dir / cid / filename
        if target.exists():
            target.unlink()

    def pick(self, cid: str, *, avoid_recent_paths: set[str] | None = None) -> str | None:
        """按分类选一张（「习惯组」优先：历史上用得多的高频率图更常被选中）。

        人不会刻意避开重复图片——而是有一套惯用表情包组，特定语境发惯用的那一张或
        语义相近的不同张；因此按历史使用频率加权随机（高频图权重更高，同时保留换图可能）。
        """
        files = self._files(cid)
        if not files:
            return None
        ordered = [f for f in files if str(self._dir / cid / f) not in (avoid_recent_paths or set())]
        if not ordered:
            ordered = files
        weights = self._frequency_weights(cid, ordered)
        return str(self._dir / cid / random.choices(ordered, weights=weights, k=1)[0])

    def _frequency_weights(self, cid: str, files: list[str]) -> list[float]:
        """按发送历史统计每张图的使用次数 → 权重（1 + 次数×1.2，封顶 6；无历史全 1）。"""
        prefs = self._load_prefs()
        counts: dict[str, int] = {}
        try:
            for item in prefs.get("sent", []):
                if str(item.get("cid") or "") == cid and item.get("path"):
                    path = str(item.get("path") or "")
                    base = str(Path(path).name)
                    counts[base] = counts.get(base, 0) + 1
        except Exception:
            counts = {}
        weights = []
        for f in files:
            n = counts.get(f, 0)
            weights.append(max(1.0, min(6.0, 1.0 + n * 1.2)))
        return weights

    def _title_to_id(self, title: str) -> str:
        for m in self._load_meta():
            if str(m.get("title") or "") == title.strip():
                return str(m.get("id") or "")
        return ""

    # ------------------------------------------------------------ 发送策略（偏好/去重/可关）

    def _load_prefs(self) -> dict[str, Any]:
        try:
            if self._prefs_file.exists():
                raw = json.loads(self._prefs_file.read_text(encoding="utf-8-sig"))
                if isinstance(raw, dict):
                    return raw
        except Exception:
            pass
        return {"sent": [], "weights": {}, "opt_out": {}, "feedback": []}

    def _save_prefs(self, prefs: dict[str, Any]) -> None:
        try:
            self._prefs_file.parent.mkdir(parents=True, exist_ok=True)
            self._prefs_file.write_text(
                json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def record_sent(self, cid: str, path: str, user: str = "") -> None:
        """记录一次发送（去重与发送日志）。"""
        prefs = self._load_prefs()
        prefs.setdefault("sent", []).insert(
            0,
            {"at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
             "cid": cid, "path": str(path), "user": str(user or "")},
        )
        prefs["sent"] = prefs["sent"][:80]
        self._save_prefs(prefs)

    def recent_sent_paths(self, cid: str, days: int = 3, user: str = "") -> set[str]:
        """近 N 天该分类发过的路径集合（同图去重用）。"""
        prefs = self._load_prefs()
        now = time.time()
        out: set[str] = set()
        try:
            for item in prefs.get("sent", []):
                at = item.get("at") or ""
                try:
                    ts = time.mktime(time.strptime(at, "%Y-%m-%d %H:%M:%S"))
                except Exception:
                    continue
                if now - ts <= days * 86400 and str(item.get("cid") or "") == cid:
                    out.add(str(item.get("path") or ""))
        except Exception:
            pass
        return out

    def sent_log(self, limit: int = 20) -> list[dict[str, Any]]:
        prefs = self._load_prefs()
        return list(prefs.get("sent", [])[:limit])

    def feedback(self, user: str, cid: str, negative: bool) -> None:
        """用户反馈（负面词/喜欢）→ 分类权重增减（±1，封顶 ±6）。"""
        prefs = self._load_prefs()
        weights = prefs.setdefault("weights", {})
        ud = weights.setdefault(str(user or ""), {})
        score = int(ud.get(cid, 0) or 0) + (-1 if negative else 1)
        ud[cid] = max(-6, min(6, score))
        prefs.setdefault("feedback", []).insert(
            0,
            {"at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
             "user": str(user or ""), "cid": cid, "negative": bool(negative)},
        )
        prefs["feedback"] = prefs["feedback"][:60]
        self._save_prefs(prefs)

    def weight_for(self, user: str, cid: str) -> float:
        """分类权重因子 0.5~1.5（按用户反馈）。"""
        prefs = self._load_prefs()
        score = int((prefs.get("weights", {}).get(str(user or ""), {}) or {}).get(cid, 0) or 0)
        return max(0.5, min(1.5, 1.0 + score * 0.08))

    def set_opt_out(self, user: str, enabled: bool) -> None:
        prefs = self._load_prefs()
        if enabled:
            prefs.setdefault("opt_out", {})[str(user or "")] = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime()
            )
        else:
            prefs.setdefault("opt_out", {}).pop(str(user or ""), None)
        self._save_prefs(prefs)

    def is_opt_out(self, user: str) -> bool:
        prefs = self._load_prefs()
        return bool(prefs.get("opt_out", {}).get(str(user or "")))

    def preference_view(self) -> dict[str, Any]:
        """策略面板数据（页面展示）。"""
        prefs = self._load_prefs()
        return {
            "opt_out": prefs.get("opt_out", {}),
            "weights": prefs.get("weights", {}),
            "feedback": list(prefs.get("feedback", [])[:10]),
            "sent": list(prefs.get("sent", [])[:20]),
        }

    # ------------------------------------------------------------ 渲染

    def render(
        self,
        text: str,
        *,
        dedup_days: int = 0,
        user: str = "",
        avoid_recent_paths: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """把文本拆成「文本段 + 表情包路径」列表，供 MessageChain 组装。

        - dedup_days > 0：按分类避开近 N 天发过的同图（记录即发送，渲染时自记）；
        - avoid_recent_paths：额外避开的路径集合。
        """
        if not text:
            return []
        result: list[dict[str, Any]] = []
        pos = 0
        for match in EMOJI_PATTERN.finditer(text):
            if match.start() > pos:
                result.append({"type": "text", "content": text[pos : match.start()]})
            cid = self._title_to_id(match.group(1).strip())
            avoid = set(avoid_recent_paths or ())
            if cid and dedup_days > 0:
                avoid |= self.recent_sent_paths(cid, days=dedup_days, user=user)
            path = self.pick(cid, avoid_recent_paths=avoid) if cid else None
            if path:
                result.append({"type": "emoji", "path": path, "cid": cid})
                if cid:
                    self.record_sent(cid, path, user)
            else:
                result.append({"type": "text", "content": ""})
            pos = match.end()
        if pos < len(text):
            result.append({"type": "text", "content": text[pos:]})
        return result

    def has_placeholder(self, text: str) -> bool:
        return bool(EMOJI_PATTERN.search(text or ""))
