"""外观状态管理：主题、明暗、自定义颜色、背景板与背景图片的持久化。

数据存放于插件数据目录（与代码分离），外观文件为 UTF-8 无 BOM 的 JSON。
"""

from __future__ import annotations

import json
import mimetypes
import re
from pathlib import Path

from .log import logger

DEFAULTS = {
    "theme": "cosmic",           # 配色主题 key（前端定义每套主题的变量）
    "scheme": "auto",            # 明暗模式：auto / light / dark
    "primary": "",               # 自定义主色，空 = 跟随主题
    "accent": "",                # 自定义辅色，空 = 跟随主题
    "canvas": "",                # 背景板颜色，空 = 跟随主题
    "canvas_enabled": False,     # 是否启用背景效果（背景色/背景图）
    "canvas_opacity": 0.8,       # 背景图透明度 0.0-1.0
    "canvas_blur": 0,            # 背景图模糊半径（px）
    "canvas_hash": "",           # 当前选中的背景图指纹
    "bg_library": [],            # 背景图库：[{hash, name, added_at}]，最多 5 张
}

_ALLOWED_FIELDS = frozenset(DEFAULTS.keys())

_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}

# 背景图库容量上限
_BG_LIBRARY_LIMIT = 5

# 缩略图边长（壁纸库小框展示用）
_THUMB_SIZE = 120


def _clamp(value: float, low: float, high: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return low


class AppearanceManager:
    """外观状态的管理入口，负责读取、合并、落盘与背景图片文件操作。"""

    def __init__(self, data_dir: Path):
        self._dir = Path(data_dir)
        self._file = self._dir / "appearance.json"
        self._bg_dir = self._dir / "backgrounds"
        self._bg_url_cache: str | None = None

    # ------------------------------------------------------------- 状态读写

    def read(self) -> dict:
        """读取当前外观状态（缺失字段用默认值补齐，并迁移旧版单图背景）。"""
        state = dict(DEFAULTS)
        try:
            if self._file.exists():
                raw = json.loads(self._file.read_text(encoding="utf-8-sig"))
                if isinstance(raw, dict):
                    for key in _ALLOWED_FIELDS:
                        if raw.get(key) is not None:
                            state[key] = raw[key]
        except Exception as exc:
            logger.warning("[Storyteller] 读取外观配置失败: %s", exc)
        state = self._normalize(state)
        return self._migrate_legacy_background(state)

    def _normalize(self, state: dict) -> dict:
        result = dict(state)
        result["scheme"] = (
            str(result.get("scheme") or "auto")
            if str(result.get("scheme") or "auto") in {"auto", "light", "dark"}
            else "auto"
        )
        result["theme"] = str(result.get("theme") or "cosmic")[:40]
        result["primary"] = str(result.get("primary") or "")[:40]
        result["accent"] = str(result.get("accent") or "")[:40]
        result["canvas"] = str(result.get("canvas") or "")[:40]
        result["canvas_enabled"] = bool(result.get("canvas_enabled"))
        result["canvas_opacity"] = _clamp(result.get("canvas_opacity", 0.8), 0.0, 1.0)
        result["canvas_blur"] = int(_clamp(result.get("canvas_blur", 0), 0, 60))
        result["canvas_hash"] = str(result.get("canvas_hash") or "")[:32]
        library = result.get("bg_library") or []
        normalized_library = []
        for item in library if isinstance(library, list) else []:
            if not isinstance(item, dict):
                continue
            entry = {
                "hash": str(item.get("hash") or "")[:32],
                "name": str(item.get("name") or "")[:80],
                "added_at": str(item.get("added_at") or "")[:40],
            }
            if entry["hash"]:
                normalized_library.append(entry)
        result["bg_library"] = normalized_library
        return result

    def _migrate_legacy_background(self, state: dict) -> dict:
        """旧版单图模式（bg.<ext>）迁移进图库，随后清理目录中的非规范文件。"""
        if not state.get("bg_library"):
            legacy = self._bg_dir / "bg.png"
            if not legacy.exists():
                legacy = self._bg_dir / "bg.jpg"
            if legacy.exists():
                try:
                    content, save_ext = self._compress_image(legacy.read_bytes())
                    import hashlib

                    fingerprint = hashlib.md5(content).hexdigest()[:12]
                    target = self._bg_dir / f"bg-{fingerprint}.{save_ext}"
                    if not target.exists():
                        target.write_bytes(content)
                    if legacy != target:
                        try:
                            legacy.unlink()
                        except OSError:
                            pass
                    state["bg_library"] = [
                        {
                            "hash": fingerprint,
                            "name": f"bg.{save_ext}",
                            "added_at": self._now_local(),
                        }
                    ]
                    state["canvas_hash"] = fingerprint
                    self._bg_url_cache = None
                    self._persist(state)
                    logger.info("[Storyteller] 旧版背景图已迁移进图库: %s", fingerprint)
                except Exception as exc:
                    logger.warning("[Storyteller] 旧版背景图迁移失败: %s", exc)
        self._purge_non_library_files()
        return state

    def _purge_non_library_files(self) -> None:
        """清理 backgrounds/ 中不属于图库规范命名（bg-<12位hex>.<png|jpg>）的文件。

        防御历史遗留：早期上传会残留 bg.png/bg.jpg 等临时文件，若不清理，
        壁纸库删空后会被旧版迁移逻辑重新拾取（表现为「删除后壁纸又蹦出来」）。
        """
        if not self._bg_dir.exists():
            return
        try:
            pattern = re.compile(r"^bg-[0-9a-f]{12}\.(png|jpg)$")
            for old in self._bg_dir.iterdir():
                if old.is_file() and not pattern.match(old.name):
                    try:
                        old.unlink()
                    except OSError:
                        pass
        except Exception as exc:
            logger.warning("[Storyteller] 清理背景目录失败: %s", exc)

    @staticmethod
    def _now_local() -> str:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        try:
            tz = ZoneInfo("Asia/Shanghai")
        except Exception:
            tz = None
        return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

    def update(self, patch: dict) -> dict:
        """按白名单合并字段并持久化，返回更新后的完整状态。"""
        if not isinstance(patch, dict):
            return self.read()
        state = self.read()
        for key, value in patch.items():
            if key in _ALLOWED_FIELDS and value is not None:
                state[key] = value
        state = self._normalize(state)
        self._persist(state)
        return state

    def restore_defaults(self) -> dict:
        """恢复默认外观并持久化。"""
        state = dict(DEFAULTS)
        self._persist(state)
        return state

    def _persist(self, state: dict) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            tmp = self._file.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self._file)
        except Exception as exc:
            logger.warning("[Storyteller] 保存外观配置失败: %s", exc)

    # ------------------------------------------------------------- 背景图片

    def _background_file(self, bg_hash: str = "") -> Path | None:
        """按指纹定位背景图文件（bg-<hash>.<ext>）；hash 为空时用当前选中。"""
        if not self._bg_dir.exists():
            return None
        if bg_hash:
            candidates = sorted(self._bg_dir.glob(f"bg-{bg_hash}.*"))
        else:
            state = self.read()
            current = state.get("canvas_hash") or ""
            candidates = sorted(self._bg_dir.glob(f"bg-{current}.*")) if current else []
        return candidates[0] if candidates else None

    def _find_file_by_hash(self, bg_hash: str) -> Path | None:
        if not bg_hash or not self._bg_dir.exists():
            return None
        candidates = sorted(self._bg_dir.glob(f"bg-{bg_hash}.*"))
        return candidates[0] if candidates else None

    def background_data_url(self, bg_hash: str = "") -> str:
        """把背景图转为 data URL（带缓存）。"""
        if bg_hash:
            bg = self._find_file_by_hash(bg_hash)
            if bg is None:
                return ""
        else:
            if self._bg_url_cache is not None:
                return self._bg_url_cache
            bg = self._background_file()
            if bg is None:
                return ""
        try:
            import base64

            raw = bg.read_bytes()
            mime = mimetypes.guess_type(bg.name)[0] or "image/png"
            data_url = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
            if not bg_hash:
                self._bg_url_cache = data_url
            return data_url
        except Exception as exc:
            logger.warning("[Storyteller] 读取背景图片失败: %s", exc)
            return ""

    def thumb_data_url(self, bg_hash: str) -> str:
        """生成缩略图 data URL（120px，壁纸库小框展示）。"""
        bg = self._find_file_by_hash(bg_hash)
        if bg is None:
            return ""
        cache_key = f"thumb_{bg_hash}_{bg.name}"
        if getattr(self, "_thumb_cache", None) is None:
            self._thumb_cache: dict = {}
        if cache_key in self._thumb_cache:
            return self._thumb_cache[cache_key]
        try:
            import base64
            import io as _io

            from PIL import Image

            img = Image.open(_io.BytesIO(bg.read_bytes()))
            img.thumbnail((_THUMB_SIZE, _THUMB_SIZE), Image.LANCZOS)
            buf = _io.BytesIO()
            img.convert("RGB").save(buf, "JPEG", quality=82)
            data_url = (
                "data:image/jpeg;base64,"
                + base64.b64encode(buf.getvalue()).decode("ascii")
            )
            self._thumb_cache[cache_key] = data_url
            return data_url
        except Exception:
            return ""

    def save_background(self, content: bytes, filename: str = "") -> dict:
        """保存背景图入库：压缩 → 去重 → 追加进图库 → 自动选中。

        图库最多 _BG_LIBRARY_LIMIT 张，超出后丢弃最早添加的一张。
        """
        if not content:
            raise ValueError("图片内容为空")
        if len(content) > 8 * 1024 * 1024:
            raise ValueError("图片超过 8 MiB 限制")
        ext = ""
        match = re.search(r"\.([A-Za-z0-9]{1,8})$", str(filename or ""))
        if match and match.group(1).lower() in _IMAGE_EXTENSIONS:
            ext = match.group(1).lower()
        if not ext:
            raise ValueError("不支持的图片格式")
        content, save_ext = self._compress_image(content)
        import hashlib

        fingerprint = hashlib.md5(content).hexdigest()[:12]
        self._bg_dir.mkdir(parents=True, exist_ok=True)
        target = self._bg_dir / f"bg-{fingerprint}.{save_ext}"
        target.write_bytes(content)
        self._bg_url_cache = None
        state = self.read()
        library = [
            item
            for item in state.get("bg_library", [])
            if item.get("hash") != fingerprint
        ]
        library.append(
            {
                "hash": fingerprint,
                "name": f"{Path(filename).name or f'bg.{save_ext}'}",
                "added_at": self._now_local(),
            }
        )
        while len(library) > _BG_LIBRARY_LIMIT:
            dropped = library.pop(0)
            self._drop_background_file(dropped.get("hash", ""))
        state["bg_library"] = library
        state["canvas_hash"] = fingerprint
        state["canvas_enabled"] = True
        self._persist(state)
        return {
            "ok": True,
            "canvas_hash": fingerprint,
            "data_url": self.background_data_url(fingerprint),
        }

    def select_background(self, bg_hash: str) -> dict:
        """切换当前背景图（指纹须在图库内）。"""
        bg_hash = str(bg_hash or "")[:32]
        state = self.read()
        if not any(item.get("hash") == bg_hash for item in state.get("bg_library", [])):
            raise ValueError("背景图不存在于图库")
        state["canvas_hash"] = bg_hash
        state["canvas_enabled"] = True
        self._persist(state)
        self._bg_url_cache = None
        return {"ok": True, "canvas_hash": bg_hash}

    def clear_background(self) -> dict:
        """删除当前选中的背景图；图库仍有其他图时自动切到最近添加的一张。"""
        state = self.read()
        current = state.get("canvas_hash") or ""
        remaining = [
            item
            for item in state.get("bg_library", [])
            if item.get("hash") != current
        ]
        if current:
            self._drop_background_file(current)
        if remaining:
            state["canvas_hash"] = remaining[-1]["hash"]
            state["canvas_enabled"] = True
        else:
            state["canvas_hash"] = ""
        state["bg_library"] = remaining
        self._persist(state)
        self._bg_url_cache = None
        return {"ok": True, "appearance": self.read()}

    def _drop_background_file(self, bg_hash: str) -> None:
        """删除图库中某指纹对应的背景文件。"""
        if not bg_hash:
            return
        for old in self._bg_dir.glob(f"bg-{bg_hash}.*"):
            try:
                old.unlink()
            except OSError:
                pass

    def background_library(self) -> list[dict]:
        """图库列表（含缩略图 data URL，供前端壁纸库展示）。"""
        state = self.read()
        result = []
        for item in state.get("bg_library", []):
            entry = dict(item)
            entry["thumb"] = self.thumb_data_url(item.get("hash", ""))
            result.append(entry)
        return result

    def _compress_image(self, content: bytes) -> tuple[bytes, str]:
        """压缩背景图：缩放到 1600px 以内，透明图存 PNG、不透明图存 JPEG。"""
        try:
            import io as _io

            from PIL import Image

            img = Image.open(_io.BytesIO(content))
            img.load()
        except Exception:
            return content, "png"
        has_alpha = img.mode in ("RGBA", "LA") or (
            img.mode == "P" and "transparency" in img.info
        )
        if has_alpha:
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")
        max_side = 1600
        width, height = img.size
        scale = min(1.0, max_side / max(width, height))
        if scale < 1.0:
            img = img.resize(
                (max(1, int(width * scale)), max(1, int(height * scale))),
                Image.LANCZOS,
            )
        try:
            buf = _io.BytesIO()
            if has_alpha:
                img.save(buf, "PNG", optimize=True)
                save_ext = "png"
            else:
                img.save(buf, "JPEG", quality=85, optimize=True)
                save_ext = "jpg"
            processed = buf.getvalue()
            if processed and len(processed) < len(content):
                return processed, save_ext
        except Exception:
            pass
        return content, "png"

