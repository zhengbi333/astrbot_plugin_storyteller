# -*- coding: utf-8 -*-
"""【为你续写的故事 · 生图】独立在线生图 API 直连（零提供方特配）。

设计要点（独立实现，参考思路不抄代码）：
- 后端模式二选一（image.backend）：
  - api：独立在线生图 API（主/备两组配置，平台归一化：openai 兼容 /y1 images/generations、
    火山方舟 seedream /v1/image_generation、MiniMax /v1/image_generation）；
  - card：AstrBot provider 的 text_to_image（默认 HTML 卡片渲染——免费文字卡片图，非 AI 绘画）；
- 超时保护：单次生成 image.api_timeout_seconds（默认 120s）；主端点失败自动尝试备端点；
- 结果落地：URL 下载或 base64 → 魔数校验（PNG/JPEG/WebP）→ 存 plugin_data/image_gen/<ts>.png；
- 记录：每次生成写 image_gen_records（内存 + JSON 文件，200 条滚动）；
- 发送与记录由 caller（main.py 触发层 / page_api 测试）负责，本模块只产出 (path, note)。
- 每日上限 image.max_daily（0=不限）；命中自然语言意图由 main.py 判断。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import time
from pathlib import Path
from typing import Any

from .log import logger

try:  # AstrBot 自带 httpx；缺失时降级（调用返回明确错误，不崩溃）
    import httpx

    _HAS_HTTPX = True
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore
    _HAS_HTTPX = False

_MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10MB
_RECORD_LIMIT = 200


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def _ext_from_bytes(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if len(image_bytes) >= 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return ".webp"
    return ""


def _extract_image_item(data: Any) -> tuple[str, str]:
    """从响应 JSON 提取图片值（url 或 base64），返回 (值, 来源)。不支持时 ('', '')。"""
    if not isinstance(data, dict):
        return "", ""
    items = data.get("data")
    if isinstance(items, list) and items and isinstance(items[0], dict):
        for key in ("url", "b64_json", "image_url", "imageUrl", "output_image", "result", "base64"):
            if items[0].get(key):
                return str(items[0][key]), key
    for key in ("url", "image_url", "result", "data_url", "b64_json", "base64"):
        if data.get(key):
            return str(data[key]), key
    images = data.get("images")
    if isinstance(images, list) and images:
        return str(images[0]), "images[0]"
    return "", ""


class ImageGen:
    """生图服务：独立 API 直连 + 卡片模式 + 记录。"""

    def __init__(self, plugin: Any, data_dir: Path):
        self._plugin = plugin
        self._data_dir = Path(data_dir) / "image_gen"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._records_file = self._data_dir / "records.json"
        self._records: list[dict[str, Any]] = self._load_records()

    # ------------------------------------------------------------- config

    def _cfg(self) -> Any:
        return getattr(self._plugin, "config", None)

    def enabled(self) -> bool:
        try:
            return bool(self._cfg().bool("image.enabled", True))
        except Exception:
            return False

    def backend(self) -> str:
        try:
            return str(self._cfg().get("image.backend", "api") or "api").strip()
        except Exception:
            return "api"

    def _server_timeout(self) -> float:
        try:
            return max(10.0, min(600.0, float(self._cfg().int("image.api_timeout_seconds", 120))))
        except Exception:
            return 120.0

    # 端点配置键与 schema 完全一致（0.148 修复：此前主端点误用 image.base_url 等键名，
    # 即使前端填写完整也永远读不到 → 报「未配置完整」）
    _ENDPOINT_KEYS = (
        ("主", "api_enabled", "api_base_url", "api_api_key", "api_model"),
        ("备", "api_backup_enabled", "api_backup_base_url", "api_backup_api_key", "api_backup_model"),
    )

    def _endpoint_values(self, enabled_key: str, base_key: str, key_key: str, model_key: str) -> tuple[bool, str, str, str]:
        cfg = self._cfg()
        try:
            enabled = cfg.get(f"image.{enabled_key}", True)
        except Exception:
            enabled = True
        try:
            base = str(cfg.get(f"image.{base_key}", "") or "").strip()
            key = str(cfg.get(f"image.{key_key}", "") or "").strip()
            model = str(cfg.get(f"image.{model_key}", "") or "").strip()
        except Exception:
            base = key = model = ""
        return bool(enabled), base, key, model

    def _endpoints(self) -> list[dict[str, str]]:
        """主/备端点列表（顺序即优先级）；未配完整自动跳过。"""
        outs: list[dict[str, str]] = []
        for label, enabled_key, base_key, key_key, model_key in self._ENDPOINT_KEYS:
            enabled, base, key, model = self._endpoint_values(enabled_key, base_key, key_key, model_key)
            if not enabled and label == "备":
                continue
            if base and key and model:
                outs.append({"label": label, "base_url": base.rstrip("/"), "api_key": key, "model": model})
        return outs

    def _missing_fields(self) -> list[str]:
        """独立 API 配置缺失项（用于明确提示，0.148）。"""
        missing: list[str] = []
        for label, enabled_key, base_key, key_key, model_key in self._ENDPOINT_KEYS:
            enabled, base, key, model = self._endpoint_values(enabled_key, base_key, key_key, model_key)
            if not enabled:
                continue
            if base or key or model:
                fields = []
                if not base:
                    fields.append("API 地址")
                if not key:
                    fields.append("API Key")
                if not model:
                    fields.append("模型")
                if fields and len(fields) < 3:
                    missing.append(f"{label}端点还差：{'、'.join(fields)}")
        return missing

    def _normalize_endpoint(self, base: str, model: str) -> str:
        """平台归一化：根据模型名/域名推断端点路径（零提供方特配=自动探测+手工可覆盖）。

        0.148 修复：base 已含 /v1 时不再拼出 /v1/v1/...（如
        https://api.siliconflow.cn/v1 → /v1/images/generations，而非双 v1 404）。
        """
        b = base.strip().rstrip("/")
        lowered = (b + " " + str(model or "")).lower()
        if "seedream" in lowered or "doubao" in lowered or "volc" in lowered or "minimax" in lowered:
            suffix = "/v1/image_generation"
        else:
            suffix = "/v1/images/generations"
        if b.endswith(suffix):
            return b
        if b.endswith("/v1"):
            return b + suffix[len("/v1"):]
        return b + suffix

    def _daily_used(self) -> int:
        today = _today()
        n = 0
        for r in self._records:
            if str(r.get("date") or "") == today:
                n += 1
        return n

    async def can_generate(self, *, kind: str = "") -> tuple[bool, str]:
        """是否允许生成（开关/每日上限）；返回 (ok, 原因)。"""
        if not self.enabled():
            return False, "生图模块未开启"
        try:
            limit = max(0, int(self._cfg().int("image.max_daily", 0) or 0))
        except Exception:
            limit = 0
        if limit > 0 and self._daily_used() >= limit:
            return False, "今日生图上限已到"
        if self.backend() == "api" and not self._endpoints():
            missing = self._missing_fields()
            return False, "独立 API 未配置完整：" + ("；".join(missing) if missing else "（base_url / api_key / model 均为空，请到「生图」页填写）")
        return True, ""

    # ------------------------------------------------------------- main 入口

    async def generate(self, prompt: str, *, size: str = "", kind: str = "text2img", reference_path: str = "", caption_user: str = "") -> tuple[str, str]:
        """生成图片，返回 (本地路径, 说明)；失败返回 ('', 原因)。"""
        started = time.monotonic()
        prompt = str(prompt or "").strip()[:3000]
        if not prompt:
            return "", "画面描述为空"
        ok, why = await self.can_generate()
        if not ok:
            return "", why
        path = ""
        note = ""
        try:
            if self.backend() == "card":
                path, note = await self._generate_via_card(prompt)
            else:
                path, note = await self._generate_via_api(prompt, size=size, reference_path=reference_path)
        except Exception as exc:
            logger.warning("[Storyteller] 生图异常: %s", exc)
            return "", f"生图失败: {exc}"
        elapsed_ms = int((time.monotonic() - started) * 1000)
        self._push_record({
            "time": _now(), "date": _today(), "kind": kind,
            "prompt": prompt[:300], "ok": bool(path), "note": note[:200],
            "elapsed_ms": elapsed_ms, "path": path[-160:],
        })
        return path, note

    async def _generate_via_api(self, prompt: str, *, size: str, reference_path: str) -> tuple[str, str]:
        endpoints = [ep for ep in self._endpoints()]
        if not endpoints:
            return "", "独立 API 未配置完整"
        errors: list[str] = []
        for ep in endpoints:
            try:
                path = await self._call_endpoint(ep, prompt, size=size, reference_path=reference_path)
                if path:
                    return path, f"已用{ep['label']}端点生成"
                errors.append(f"{ep['label']}无返回图片")
            except Exception as exc:
                errors.append(f"{ep['label']}失败: {_first_line(str(exc))}")
        return "", "；".join(errors[-4:])

    async def _call_endpoint(self, ep: dict[str, str], prompt: str, *, size: str, reference_path: str) -> str:
        if not _HAS_HTTPX:
            raise RuntimeError("环境缺少 httpx 依赖，无法生图")
        url = self._normalize_endpoint(ep["base_url"], ep["model"])
        headers = {"Authorization": f"Bearer {ep['api_key']}", "Content-Type": "application/json"}
        sizing = size or "1024x1024"
        payload: dict[str, Any] = {"model": ep["model"], "prompt": prompt, "size": sizing}
        if "image_generation" in url:
            payload["response_format"] = "url"
            payload["watermark"] = False
        timeout = httpx.Timeout(self._server_timeout(), connect=8, write=20, pool=8)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            text = resp.text or ""
            if resp.status_code >= 400:
                # 自适应兼容（0.148）：部分平台（如硅基流动）参数名是 image_size 而非 size——
                # 400 时用 image_size 重试一次（通用兼容，非提供方特配）
                if "size" in (text or "").lower() and "image_size" not in payload:
                    payload["image_size"] = sizing
                    payload.pop("size", None)
                    resp = await client.post(url, headers=headers, json=payload)
                    text = resp.text or ""
                    if resp.status_code >= 400:
                        raise RuntimeError(f"HTTP {resp.status_code} {_first_line(text)}")
                else:
                    raise RuntimeError(f"HTTP {resp.status_code} {_first_line(text)}")
            try:
                data = json.loads(text) if text else {}
            except Exception:
                raise RuntimeError(f"响应不是 JSON: {_first_line(text)}")
            value, src = _extract_image_item(data)
            if not value:
                raise RuntimeError("响应无图片数据")
            return await self._materialize(value, src)

    async def _materialize(self, value: str, src: str) -> str:
        if not _HAS_HTTPX and not value.lower().startswith("data:image"):
            raise RuntimeError("环境缺少 httpx 依赖，无法下载图片")
        if value.lower().startswith("data:image") and "," in value:
            _, encoded = value.split(",", 1)
            return await self._save_base64(encoded)
        if re.fullmatch(r"[A-Za-z0-9+/=\s]+", value) and len(value) > 128:
            return await self._save_base64(value)
        # URL 下载
        timeout = httpx.Timeout(self._server_timeout(), connect=8, write=20, pool=8)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(value)
            if resp.status_code >= 400:
                raise RuntimeError(f"图片下载 HTTP {resp.status_code}")
            image_bytes = resp.content
        return await self._save_bytes(image_bytes)

    async def _save_base64(self, encoded: str) -> str:
        compact = re.sub(r"\s+", "", str(encoded or ""))
        padded = compact + ("=" * (-len(compact) % 4))
        try:
            image_bytes = base64.b64decode(padded, validate=True)
        except (binascii.Error, ValueError):
            raise RuntimeError("图片 base64 无效")
        return await self._save_bytes(image_bytes)

    async def _save_bytes(self, image_bytes: bytes) -> str:
        ext = _ext_from_bytes(image_bytes)
        if not ext:
            raise RuntimeError("不是受支持的 PNG/JPEG/WebP")
        if len(image_bytes) > _MAX_IMAGE_BYTES:
            raise RuntimeError("图片超过 10MB")
        path = self._data_dir / f"img_{int(time.time() * 1000)}{ext}"
        path.write_bytes(image_bytes)
        return str(path)

    async def _generate_via_card(self, prompt: str) -> tuple[str, str]:
        """AstrBot provider 的 text_to_image（默认 = HTML 卡片渲染，免费文字卡片图）。"""
        try:
            provider_id = str(self._cfg().get("image.card_provider_id", "") or "").strip()
        except Exception:
            provider_id = ""
        provider = None
        context = getattr(self._plugin, "context", None)
        if context is not None and provider_id:
            getter = getattr(context, "get_provider_by_id", None)
            if callable(getter):
                provider = getter(provider_id)
        if provider is None:
            return "", "卡片模式未找到所选 provider（先到「生图」页选择）"
        t2i = getattr(provider, "text_to_image", None)
        if not callable(t2i):
            return "", "该 provider 无 text_to_image 接口"
        try:
            result = await t2i(prompt, return_url=True)
        except Exception as exc:
            return "", f"卡片渲染失败: {_first_line(str(exc))}"
        result = str(result or "")
        if (result.startswith("data:image") and "," in result) or re.fullmatch(r"[A-Za-z0-9+/=\s]+", result[:64]):
            return await self._materialize(result, "card")
        if result.startswith("http"):
            return await self._materialize(result, "card")
        return "", "卡片渲染未返回图片（可尝试选择其它 provider）"

    # ------------------------------------------------------------- records

    def _load_records(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self._records_file.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _push_record(self, rec: dict[str, Any]) -> None:
        self._records.insert(0, rec)
        del self._records[_RECORD_LIMIT:]
        try:
            self._records_file.write_text(json.dumps(self._records, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(self._records[:max(1, min(50, int(limit or 20)))])

    def stats(self) -> dict[str, Any]:
        today = _today()
        missing = self._missing_fields() if self.backend() == "api" and not self._endpoints() else []
        return {
            "enabled": self.enabled(),
            "backend": self.backend(),
            "endpoints_ready": 0 if self.backend() == "api" and not self._endpoints() else (len(self._endpoints()) if self.backend() == "api" else 1),
            "today_count": self._daily_used(),
            "total_count": len(self._records),
            "missing": missing,
        }


def _first_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or ""))[:160]


# ---------------------------------------------------------------- 意图检测（自然语言快判）

_IMAGE_TRIGGER_RE = re.compile(
    r"(?:^|[\s，。！？?；;,、]|帮我|给我|请你|请|快|麻烦|拜托|帮你|给你|您|你|自己|我自己|好的|好|嗯|行|噢|哦|呀|啊|然后)("
    r"画(?:[一]?[张幅个只条头朵座]|一下|好)?|"
    r"生成(?:[一]?[张幅个只条头朵座])?|"
    r"做(?:[一]?[张幅个只条头朵座])?|"
    r"来(?:[一]?[张幅个只条头朵座])?|"
    r"照(?:[一]?[张幅个只条头朵座])?|"
    r"拍(?:[一]?[张幅个只条头朵座])?"
    r")"
)

# 0.177 修正：句尾语气词与残余助词（拍一张吧／你拍一张呢）
_TRAIL_WORDS = ("吧", "啦", "呗", "呀", "哦", "呢", "嘛", "噢", "啊")

_NEGATIVE_HITS = ("画饼", "画重点", "画大饼", "画风", "画质", "画画软件", "画图板")

# 画面对象词（无量化词时要求尾段像「可画的画面目标」）
_PICTURE_WORDS = ("图", "照片", "相片", "图片", "头像", "壁纸", "海报", "画", "自拍", "写真", "人像", "合照", "立绘", "风景", "表情", "照")

# 0.177 语义修正：非生图的「聊天回顾/自指」——动作发生在过去且主语是“我/我们”
# （“我拍了张照”“刚才画了一张”→ 描述用户自己干的事，不是请 bot 生成）
_CHAT_RECALL_RE = re.compile(r"(我|我们|咱|我自己|自己)(刚|刚刚|刚才|已经)?(拍|画|照|生成)(了|过|的)")

# 否定/不愿（“别拍”“不想画”“拍不了”）
_NEGATE_RE = re.compile(r"(不想?|别|不用|无法|不能|拍不了|画不了|生成不了)(拍|画|照|生成|来|做)")

# 0.177 语义修正：「生成后发送/索图」用语——不是排除依据，而是从画面描述里剥掉
# （“拍个照发我”→“照片”，发我/发给你/给我看看 都是「要图」的信号）
_SEND_NOISE = ("发给我看一看", "发给我看看", "发给你看看", "发给我", "发给你", "发给他", "发给她",
               "发过来", "发过去", "发来看看", "发来看", "发我", "发你", "发一下", "发一张", "发个",
               "发出去", "发消息", "给我看看", "给我看", "我看看", "发张")


def detect_image_intent(text: str) -> str:
    """检测「明确请求画/生图」意图，返回画面描述（空串=未命中）。

    克制设计：仅当文本含绘画/拍照触发词（画/生成/做/来/照/拍）且随后有画面对象
    （照片/自拍/图等，或有明确量词「一张/一下」）才命中；「画饼」「画重点」等
    惯用语、否定（别拍/拍不了）、聊天回顾（我拍了张照）明确排除。
    **「发我/发给你/给我看看」是索图信号而非聊天**（0.177 修正 0.176 的过宽排除）——
    从描述里剥掉后命中，画面描述返回剩余部分（如「拍个照发我」→「照片」）。
    """
    raw = str(text or "").strip()
    if not raw or len(raw) > 300:
        return ""
    for neg in _NEGATIVE_HITS:
        if neg in raw:
            return ""
    if _NEGATE_RE.search(raw):
        return ""
    if _CHAT_RECALL_RE.search(raw):
        return ""
    m = _IMAGE_TRIGGER_RE.search(raw)
    if not m:
        return ""
    tail = re.sub(r"[。！!？?\s]*$", "", raw[m.end():]).strip()
    # 剥掉生成后发送/索图用语，保留真正的画面描述
    for noise in sorted(_SEND_NOISE, key=len, reverse=True):
        tail = tail.replace(noise, "")
    # 0.177：句尾语气词剥离（拍一张吧 / 你拍一张呢）
    while tail and tail[-1] in _TRAIL_WORDS:
        tail = tail[:-1].strip()
    tail = re.sub(r"[，。！!？?、\s]+", "", tail).strip()
    if not tail:
        # 0.177：触发词+量词吃掉了全句、只剩索图/语气（“拍一张发我”“你自己拍一张吧”）——
        # 「拍/照」系列有“照片”默认语义，返回通用描述；其余无画面内容仍拒绝（“给我画个”）。
        if re.search(r"拍|照", m.group(1)):
            return "照片"
        return ""
    # 残余短词归一（「拍个照发我」剥掉后只剩「照」）
    if tail in ("照", "拍"):
        tail = "照片"
    quantifier = bool(re.search(r"[一]?[张幅个只条头朵座]|一下|好", m.group(1)))
    if not quantifier and not any(w in tail[:60] for w in _PICTURE_WORDS):
        return ""  # 裸「画/拍」且尾段不像画面对象（画完了/画重点等）→ 不拦截
    return tail[:200]