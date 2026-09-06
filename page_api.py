"""Web API：供 WebUI 面板调用的后端接口。

全部路由以 /astrbot_plugin_storyteller 为前缀，通过 context.register_web_api 注册，
前端使用 AstrBotPluginPage bridge（apiGet/apiPost/upload）调用。

请求对象三级回退：
1. AstrBot 面板运行时的 quart 风格代理（call_request_view 路径会绑定它）；
2. astrbot.api.web 的请求代理（旧调用路径）；
3. quart 自带 request（极老版本）。
响应对象同理优先 astrbot.api.web，缺失时回退 quart jsonify。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from pathlib import Path
from typing import Any

from . import PLUGIN_DISPLAY, PLUGIN_NAME, PLUGIN_VERSION
from .config import ConfigView
from .intercept import placeholder_list
from .log import logger
from .models import chat_text
from .presence import build_presence_generate_prompt, parse_presence
from .schedule import build_schedule_generate_prompt, parse_schedule
from .ui_state import KNOWN_TABS
from .voice import VOICE_EXAMPLES, build_generate_prompt, parse_generated_voice

CONFIG_FILE_NAME = "astrbot_plugin_storyteller_config.json"

try:  # pragma: no cover
    from astrbot.api.web import error_response, json_response

    _HAS_WEB_RESPONSE = True
except Exception:  # pragma: no cover
    _HAS_WEB_RESPONSE = False
    from quart import jsonify  # type: ignore

try:  # pragma: no cover
    from astrbot.dashboard.asgi_runtime import request as _request

    _REQUEST_SOURCE = "asgi"
except Exception:  # pragma: no cover
    try:  # pragma: no cover
        from astrbot.api.web import request as _request

        _REQUEST_SOURCE = "web"
    except Exception:  # pragma: no cover
        from quart import request as _request  # type: ignore

        _REQUEST_SOURCE = "quart"


async def _ok(data: Any = None) -> Any:
    if _HAS_WEB_RESPONSE:
        return json_response(data)
    return jsonify({} if data is None else data)


async def _fail(message: str, status_code: int = 400) -> Any:
    if _HAS_WEB_RESPONSE:
        return error_response(message, status_code=status_code)
    return jsonify({"status": "error", "message": message}), status_code


async def _json_body(default: Any = None) -> Any:
    """读取 JSON 请求体，兼容三种请求来源。"""
    try:
        if _REQUEST_SOURCE == "asgi":
            # quart 风格：request.json 是 async property
            value = getattr(_request, "json", None)
            if inspect.isawaitable(value):
                return await value
            if callable(value):
                result = value()
                return await result if inspect.isawaitable(result) else result
            return value if value is not None else default
        if _REQUEST_SOURCE == "web":
            return await _request.json(default=default)
        get_json = getattr(_request, "get_json", None)
        if callable(get_json):
            result = get_json(silent=True)
            return await result if inspect.isawaitable(result) else result
        return getattr(_request, "json", default)
    except Exception:
        return default


async def _request_files() -> Any:
    """读取上传文件，兼容新 API 的 awaitable 与旧版 Quart 的同步属性。"""
    try:
        files = getattr(_request, "files", None)
        if callable(files):
            files = files()
        if inspect.isawaitable(files):
            files = await files
        return files or {}
    except Exception:
        return {}


def _dedupe_closet_items(items: list[dict[str, Any]], existing_names: list[str]) -> list[dict[str, Any]]:
    """生成衣柜去重（0.151）：与现有衣柜名称完全/高度相似（>0.82）的剔除，列表内部同样去重。

    用 difflib 相似度做轻量判断（标准库，零依赖），保证「生成与原本大面积重合」不再发生。
    """
    from difflib import SequenceMatcher

    def similar(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        return SequenceMatcher(None, a, b).ratio()

    existing = [str(n or "").strip() for n in (existing_names or []) if str(n or "").strip()]
    out: list[dict[str, Any]] = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()
        if not name or len(name) < 2:
            continue
        if name in existing or any(similar(name, n) >= 0.82 for n in existing):
            continue
        if any(similar(name, str(o.get("name") or "")) >= 0.82 for o in out):
            continue
        out.append(it)
    return out


async def _save_upload(upload: Any, target: Path) -> None:
    """把上传文件落盘（优先 save 接口，缺失时退化为 read + 写文件）。"""
    save = getattr(upload, "save", None)
    if callable(save):
        try:
            result = save(target)
            if inspect.isawaitable(result):
                await result
            return
        except TypeError:
            pass
    read = getattr(upload, "read", None)
    if callable(read):
        result = read()
        data = await result if inspect.isawaitable(result) else result
        if isinstance(data, bytes):
            target.write_bytes(data)


def _query(key: str, default: Any = None) -> Any:
    try:
        args = getattr(_request, "args", None)
        if args is not None:
            return args.get(key, default)
        return _request.query.get(key, default)
    except Exception:
        return default


class StorytellerWebApi:
    """面板后端接口：健康状态与外观控制。"""

    def __init__(self, plugin: Any):
        self._plugin = plugin

    def mount(self, context: Any) -> None:
        if not hasattr(context, "register_web_api"):
            return
        register = context.register_web_api
        prefix = f"/{PLUGIN_NAME}"
        routes = [
            (f"{prefix}/health", self.health, ["GET"], "Storyteller health"),
            (f"{prefix}/appearance", self.appearance_read, ["GET"], "Storyteller appearance read"),
            (f"{prefix}/appearance/update", self.appearance_update, ["POST"], "Storyteller appearance update"),
            (f"{prefix}/appearance/reset", self.appearance_reset, ["POST"], "Storyteller appearance reset"),
            (f"{prefix}/appearance/background", self.appearance_background_upload, ["POST"], "Storyteller background upload"),
            (f"{prefix}/appearance/background/select", self.appearance_background_select, ["POST"], "Storyteller background select"),
            (f"{prefix}/appearance/background/clear", self.appearance_background_clear, ["POST"], "Storyteller background clear"),
            (f"{prefix}/config/schema", self.config_schema, ["GET"], "Storyteller config schema"),
            (f"{prefix}/config/module/update", self.config_module_update, ["POST"], "Storyteller config module update"),
            (f"{prefix}/config/module/reset", self.config_module_reset, ["POST"], "Storyteller config module reset"),
            (f"{prefix}/intercept/status", self.intercept_status, ["GET"], "Storyteller intercept status"),
            (f"{prefix}/intercept/requests", self.intercept_requests, ["GET"], "Storyteller intercepted LLM requests"),
            (f"{prefix}/intercept/user_requests", self.intercept_user_requests, ["GET"], "Storyteller intercepted user requests"),
            (f"{prefix}/intercept/clear", self.intercept_clear, ["POST"], "Storyteller intercept clear"),
            (f"{prefix}/intercept/sent", self.intercept_sent, ["GET"], "Storyteller recently sent LLM requests"),
            (f"{prefix}/debounce/status", self.debounce_status, ["GET"], "Storyteller debounce status"),
            (f"{prefix}/debounce/history", self.debounce_history, ["GET"], "Storyteller debounce history"),
            (f"{prefix}/debounce/flush", self.debounce_flush, ["POST"], "Storyteller debounce flush session"),
            (f"{prefix}/debounce/logs", self.debounce_logs, ["GET"], "Storyteller debounce module logs"),
            (f"{prefix}/debounce/smart_log", self.debounce_smart_log, ["GET"], "Storyteller debounce smart judge log"),
            (f"{prefix}/voice", self.voice_read, ["GET"], "Storyteller voice profile read"),
            (f"{prefix}/voice/update", self.voice_update, ["POST"], "Storyteller voice profile update"),
            (f"{prefix}/voice/generate", self.voice_generate, ["POST"], "Storyteller voice profile generate"),
            (f"{prefix}/voice/examples", self.voice_examples, ["GET"], "Storyteller voice profile examples"),
            (f"{prefix}/voice/personas", self.voice_personas, ["GET"], "Storyteller available personas for voice gen"),
            (f"{prefix}/persona/read", self.persona_read, ["GET"], "Storyteller persona injection read"),
            (f"{prefix}/persona/update", self.persona_update, ["POST"], "Storyteller persona injection update"),
            (f"{prefix}/persona/generate", self.persona_generate, ["POST"], "Storyteller persona injection generate"),
            (f"{prefix}/persona/personas", self.voice_personas, ["GET"], "Storyteller available AstrBot personas"),
            (f"{prefix}/rewrite/buffer", self.rewrite_buffer, ["GET"], "Storyteller rewrite buffer (polish in/out)"),
            (f"{prefix}/presence", self.presence_read, ["GET"], "Storyteller presence read"),
            (f"{prefix}/presence/evolve", self.presence_evolve, ["POST"], "Storyteller presence manual evolve"),
            (f"{prefix}/presence/update", self.presence_update, ["POST"], "Storyteller presence update"),
            (f"{prefix}/presence/generate", self.presence_generate, ["POST"], "Storyteller presence generate"),
            (f"{prefix}/schedule", self.schedule_read, ["GET"], "Storyteller schedule read"),
            (f"{prefix}/schedule/update", self.schedule_update, ["POST"], "Storyteller schedule update"),
            (f"{prefix}/schedule/generate", self.schedule_generate, ["POST"], "Storyteller schedule generate"),
            (f"{prefix}/schedule/prompt_preview", self.schedule_prompt_preview, ["GET"], "Storyteller schedule prompt preview"),
            (f"{prefix}/proactive/status", self.proactive_status, ["GET"], "Storyteller proactive status"),
            (f"{prefix}/proactive/trigger", self.proactive_trigger, ["POST"], "Storyteller proactive trigger"),
            (f"{prefix}/proactive/preview", self.proactive_preview, ["POST"], "Storyteller proactive preview"),
            (f"{prefix}/proactive/prompt_preview", self.proactive_prompt_preview, ["GET"], "Storyteller proactive prompt preview"),
            (f"{prefix}/proactive/targets", self.proactive_targets, ["POST"], "Storyteller proactive targets manage"),
            (f"{prefix}/token/stats", self.token_stats, ["GET"], "Storyteller token stats"),
            (f"{prefix}/models/providers", self.model_providers, ["GET"], "Storyteller model providers"),
            (f"{prefix}/emoji/categories", self.emoji_categories, ["GET"], "Storyteller emoji categories"),
            (f"{prefix}/emoji/category/add", self.emoji_category_add, ["POST"], "Storyteller emoji category add"),
            (f"{prefix}/emoji/category/update", self.emoji_category_update, ["POST"], "Storyteller emoji category update"),
            (f"{prefix}/emoji/category/remove", self.emoji_category_remove, ["POST"], "Storyteller emoji category remove"),
            (f"{prefix}/emoji/upload", self.emoji_upload, ["POST"], "Storyteller emoji upload"),
            (f"{prefix}/emoji/remove", self.emoji_remove, ["POST"], "Storyteller emoji remove"),
            (f"{prefix}/emoji/prefs", self.emoji_prefs, ["GET"], "Storyteller emoji prefs"),
            (f"{prefix}/emoji/optout", self.emoji_optout, ["POST"], "Storyteller emoji opt out"),
            (f"{prefix}/send/status", self.send_status, ["GET"], "Storyteller send buffer status"),
            (f"{prefix}/send/purge", self.send_purge, ["POST"], "Storyteller send buffer purge"),
            (f"{prefix}/mind", self.mind_read, ["GET"], "Storyteller mind read"),
            (f"{prefix}/memory", self.memory_read, ["GET"], "Storyteller memory read"),
            (f"{prefix}/mind/generate", self.mind_generate, ["POST"], "Storyteller mind manual generate"),
            (f"{prefix}/mind/search", self.mind_search, ["POST"], "Storyteller mind manual search"),
            (f"{prefix}/mind/delete", self.mind_delete, ["POST"], "Storyteller mind delete entry"),
            (f"{prefix}/diary", self.diary_read, ["GET"], "Storyteller diary read"),
            (f"{prefix}/diary/prompt_preview", self.diary_prompt_preview, ["GET"], "Storyteller diary prompt preview"),
            (f"{prefix}/wardrobe", self.wardrobe_read, ["GET"], "Storyteller wardrobe read"),
            (f"{prefix}/wardrobe/outfit", self.wardrobe_outfit_update, ["POST"], "Storyteller wardrobe outfit update"),
            (f"{prefix}/wardrobe/generate", self.wardrobe_generate, ["POST"], "Storyteller wardrobe generate outfit"),
            (f"{prefix}/wardrobe/generate_batch", self.wardrobe_generate_batch, ["POST"], "Storyteller wardrobe generate preview batch (10)"),
            (f"{prefix}/wardrobe/apply_batch", self.wardrobe_apply_batch, ["POST"], "Storyteller wardrobe apply preview batch"),
            (f"{prefix}/wardrobe/replace_all", self.wardrobe_replace_all, ["POST"], "Storyteller wardrobe replace all (keep important)"),
            (f"{prefix}/wardrobe/pin", self.wardrobe_pin, ["POST"], "Storyteller wardrobe manual important mark"),
            (f"{prefix}/wardrobe/closet/add", self.wardrobe_closet_add, ["POST"], "Storyteller wardrobe closet add"),
            (f"{prefix}/wardrobe/closet/remove", self.wardrobe_closet_remove, ["POST"], "Storyteller wardrobe closet remove"),
            (f"{prefix}/relationships", self.relationships_read, ["GET"], "Storyteller relationships read"),
            (f"{prefix}/relationships/update", self.relationships_update, ["POST"], "Storyteller relationship manual update"),
            (f"{prefix}/ui/tab_order", self.ui_tab_order_read, ["GET"], "Storyteller UI tab order read"),
            (f"{prefix}/ui/tab_order", self.ui_tab_order_update, ["POST"], "Storyteller UI tab order update"),
            (f"{prefix}/diag/runtime", self.diag_runtime, ["GET"], "Storyteller runtime diagnostics"),
            (f"{prefix}/diag/checks", self.diag_checks, ["GET"], "Storyteller module self-check definitions"),
            (f"{prefix}/diag/check", self.diag_check, ["POST"], "Storyteller single module self-check"),
            (f"{prefix}/diag/run", self.diag_run, ["POST"], "Storyteller read-only self-checks (no LLM)"),
            (f"{prefix}/diag/llm_test", self.diag_llm_test, ["POST"], "Storyteller sequential real LLM ping"),
            (f"{prefix}/identity/editor", self.identity_editor, ["GET"], "Storyteller identity anchor editor"),
            (f"{prefix}/logs", self.logs, ["GET"], "Storyteller runtime logs"),
            (f"{prefix}/thanks/images", self.thanks_images, ["GET"], "Storyteller thanks avatars"),
            (f"{prefix}/image/status", self.image_status, ["GET"], "Storyteller image gen status"),
            (f"{prefix}/image/generate", self.image_generate, ["POST"], "Storyteller image gen (test generate)"),
        ]
        for route, handler, methods, desc in routes:
            register(route, handler, methods, desc)

    # ------------------------------------------------------------- 生图

    async def image_status(self) -> Any:
        """生图状态：开关/后端模式/端点就绪/今日与总次数/最近记录。"""
        gen = getattr(self._plugin, "image_gen", None)
        if gen is None:
            return await _fail("生图模块未初始化")
        return await _ok({"status": gen.stats(), "records": gen.recent(20)})

    async def image_generate(self) -> Any:
        """试生成一张（前端测试）：prompt 必填；返回 ok 与说明/路径。"""
        gen = getattr(self._plugin, "image_gen", None)
        if gen is None:
            return await _fail("生图模块未初始化")
        body = await _json_body()
        prompt = str((body or {}).get("prompt") or "").strip()
        if not prompt:
            return await _fail("请填写画面描述")
        path, note = await gen.generate(prompt, kind="test")
        if not path:
            return await _fail(note or "生成失败")
        return await _ok({"path": path, "note": note})

    # ------------------------------------------------------------- 状态

    async def health(self) -> Any:
        return await _ok(
            {
                "ok": True,
                "display": PLUGIN_DISPLAY,
                "version": PLUGIN_VERSION,
                "data_dir": str(self._plugin.data_dir),
            }
        )

    # ------------------------------------------------------------- 外观

    async def appearance_read(self) -> Any:
        logger.info("读取外观")
        return await _ok({"appearance": self._appearance_payload()})

    async def appearance_update(self) -> Any:
        body = await _json_body(default={})
        if not isinstance(body, dict):
            return await _fail("请求体必须是 JSON 对象")
        logger.info("保存外观: %s", body)
        self._plugin.appearance.update(body)
        return await _ok({"appearance": self._appearance_payload()})

    async def appearance_reset(self) -> Any:
        logger.info("恢复默认外观")
        self._plugin.appearance.restore_defaults()
        return await _ok({"appearance": self._appearance_payload()})

    def _appearance_payload(self) -> dict:
        """外观完整载荷：状态 + 当前背景图 data URL + 壁纸库（含缩略图）。"""
        state = self._plugin.appearance.read()
        payload = dict(state)
        payload["bg_data_url"] = self._plugin.appearance.background_data_url()
        payload["bg_library"] = self._plugin.appearance.background_library()
        return payload

    # ------------------------------------------------------------- 配置

    def _load_config_schema(self) -> dict:
        schema_path = Path(__file__).with_name("_conf_schema.json")
        try:
            data = json.loads(schema_path.read_text(encoding="utf-8-sig"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _config_file_path(self) -> Path:
        """插件配置文件（与 AstrBot 配置系统一致）：<data>/config/<name>_config.json。"""
        data_root = self._plugin.data_dir.parent.parent
        return data_root / "config" / CONFIG_FILE_NAME

    def _read_config_file(self) -> dict:
        path = self._config_file_path()
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            return raw if isinstance(raw, dict) else {}
        except Exception as exc:
            logger.warning("[Storyteller] 读取配置文件失败: %s", exc)
            return {}

    def config_values(self, schema: dict) -> dict:
        view = ConfigView(self._plugin.raw_config)
        result: dict[str, dict] = {}
        for module, module_schema in schema.items():
            items = module_schema.get("items") if isinstance(module_schema, dict) else None
            if not isinstance(items, dict):
                continue
            result[module] = {}
            for key, item_schema in items.items():
                if not isinstance(item_schema, dict):
                    continue
                result[module][key] = view.get(f"{module}.{key}", item_schema.get("default"))
        return result

    @staticmethod
    def _coerce_config_value(value: Any, value_type: str, item_schema: dict) -> Any:
        if value_type == "bool":
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on", "开", "开启"}
            return bool(value)
        if value_type == "int":
            try:
                return int(value)
            except (TypeError, ValueError):
                return int(item_schema.get("default", 0) or 0)
        if value_type == "float":
            try:
                return float(value)
            except (TypeError, ValueError):
                return float(item_schema.get("default", 0.0) or 0.0)
        return str(value or "")[:2000]

    async def config_schema(self) -> Any:
        schema = self._load_config_schema()
        config_file = self._config_file_path()
        return await _ok(
            {
                "schema": schema,
                "values": self.config_values(schema),
                "config_file": CONFIG_FILE_NAME,
                "config_file_path": str(config_file),
                "config_file_exists": config_file.exists(),
            }
        )

    async def config_module_update(self) -> Any:
        body = await _json_body(default={})
        module = str(body.get("module") or "")
        values = body.get("values")
        if not module or not isinstance(values, dict):
            return await _fail("缺少 module 或 values 参数")
        schema = self._load_config_schema()
        module_schema = schema.get(module)
        if not isinstance(module_schema, dict):
            return await _fail(f"未知配置模块: {module}")
        items = module_schema.get("items") if isinstance(module_schema.get("items"), dict) else {}
        raw = self._read_config_file()
        current = raw.setdefault(module, {})
        for key, value in values.items():
            item_schema = items.get(key)
            if not isinstance(item_schema, dict):
                continue
            current[key] = self._coerce_config_value(
                value, str(item_schema.get("type", "string")), item_schema
            )
        try:
            path = self._config_file_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(raw, ensure_ascii=False, indent=2),
                encoding="utf-8-sig",
            )
        except Exception as exc:
            logger.warning("[Storyteller] 保存配置文件失败: %s", exc)
            return await _fail(f"保存配置失败: {exc}")
        self._plugin.raw_config = raw
        self._plugin.config = ConfigView(raw)
        logger.info("[Storyteller] 配置已保存: module=%s values=%s", module, current)
        return await _ok(
            {"ok": True, "values": self.config_values(schema).get(module, {})}
        )

    async def config_module_reset(self) -> Any:
        body = await _json_body(default={})
        module = str(body.get("module") or "")
        schema = self._load_config_schema()
        if module not in schema:
            return await _fail(f"未知配置模块: {module}")
        raw = self._read_config_file()
        raw.pop(module, None)
        try:
            path = self._config_file_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(raw, ensure_ascii=False, indent=2),
                encoding="utf-8-sig",
            )
        except Exception as exc:
            logger.warning("[Storyteller] 重置配置失败: %s", exc)
            return await _fail(f"重置配置失败: {exc}")
        self._plugin.raw_config = raw
        self._plugin.config = ConfigView(raw)
        logger.info("[Storyteller] 配置模块已重置: %s", module)
        return await _ok({"ok": True, "values": self.config_values(schema).get(module, {})})

    # ------------------------------------------------------------- 拦截

    async def intercept_status(self) -> Any:
        limit = _query("limit", 20)
        return await _ok(
            {
                "enabled": self._plugin.config.bool("intercept.enabled", True),
                "mode": str(self._plugin.config.get("intercept.mode", "接管走主链") or "接管走主链"),
                "max_records": self._plugin.config.int("intercept.max_records", 50),
                "llm_request_count": len(self._plugin.intercept.llm_requests(int(limit) if str(limit).isdigit() else 20)),
                # 0.178：占位符清单由后端下发（与 intercept.TEMPLATE_PLACEHOLDERS 同源），
                # 前端不再硬编码（此前硬编码 14 个、缺 {穿搭} 与 {回复}）
                "placeholders": placeholder_list(),
            }
        )

    async def intercept_requests(self) -> Any:
        limit = _query("limit", 20)
        try:
            count = max(1, min(200, int(limit)))
        except (TypeError, ValueError):
            count = 20
        return await _ok({"items": self._plugin.intercept.llm_requests(count)})

    async def intercept_user_requests(self) -> Any:
        limit = _query("limit", 20)
        try:
            count = max(1, min(200, int(limit)))
        except (TypeError, ValueError):
            count = 20
        return await _ok({"items": self._plugin.intercept.user_requests(count)})

    async def intercept_clear(self) -> Any:
        self._plugin.intercept.clear()
        logger.info("拦截记录已清空")
        return await _ok({"ok": True})

    async def intercept_sent(self) -> Any:
        """最近发送给对话用 LLM 的请求快照（不区分模式，实时面板）。"""
        limit = _query("limit", 20)
        try:
            count = max(1, min(100, int(limit)))
        except (TypeError, ValueError):
            count = 20
        return await _ok({"items": self._plugin.sent.sent(count)})

    # ------------------------------------------------------------- 防抖

    async def debounce_status(self) -> Any:
        return await _ok(
            {
                "enabled": self._plugin.debounce.enabled(),
                "private_only": self._plugin.debounce.private_only(),
                "window": self._plugin.debounce._window(),
                "adaptive": self._plugin.debounce._adaptive(),
                "sessions": self._plugin.debounce.active_sessions(),
            }
        )

    async def debounce_history(self) -> Any:
        return await _ok({"items": self._plugin.debounce.history(30)})

    async def debounce_flush(self) -> Any:
        body = await _json_body(default={})
        session_id = str(body.get("session_id") or "")[:200] if isinstance(body, dict) else ""
        if not session_id:
            return await _fail("缺少 session_id 参数")
        ok = await self._plugin.debounce.flush(session_id)
        if not ok:
            return await _fail("会话不存在或已结算")
        return await _ok({"ok": True})

    async def debounce_logs(self) -> Any:
        """防抖模块日志（内存环形，按模块过滤）。"""
        from .log import memory_logs

        limit = _query("limit", 120)
        try:
            count = max(1, min(500, int(limit)))
        except (TypeError, ValueError):
            count = 120
        return await _ok({"items": memory_logs("防抖", count)})

    async def debounce_smart_log(self) -> Any:
        """智能判定面板数据：判定事件 + 活动会话状态（含实时剩余秒）。"""
        limit = _query("limit", 30)
        try:
            count = max(1, min(100, int(limit)))
        except (TypeError, ValueError):
            count = 30
        report = self._plugin.debounce.smart_report(count)
        return await _ok(report)

    # ------------------------------------------------------------- 日志

    async def logs(self) -> Any:
        """运行时日志：带 module 参数返回该模块内存日志；不带则返回 storyteller.log 文件尾部。"""
        module = str(_query("module", "") or "").strip()
        if module:
            from .log import memory_logs

            limit = _query("limit", 120)
            try:
                count = max(1, min(500, int(limit)))
            except (TypeError, ValueError):
                count = 120
            return await _ok({"logs": memory_logs(module, count), "module": module, "file": False})
        log_path = self._plugin.data_dir / "storyteller.log"
        content = ""
        try:
            if log_path.exists():
                raw = log_path.read_text(encoding="utf-8", errors="replace")
                content = "\n".join(raw.splitlines()[-200:])
        except Exception as exc:
            content = f"读取日志失败: {exc}"
        return await _ok({"logs": content, "path": str(log_path), "file": True})

    # ------------------------------------------------------------- 背景图片

    async def appearance_background_upload(self) -> Any:
        files = await _request_files()
        upload = files.get("file") if files else None
        if upload is None:
            return await _fail("缺少文件字段 file")
        filename = str(getattr(upload, "filename", "") or "")
        logger.info("收到背景图上传: name=%s", filename)
        try:
            content = await self._read_upload(upload)
            result = self._plugin.appearance.save_background(content, filename)
        except ValueError as exc:
            logger.warning("背景图校验失败: %s", exc)
            return await _fail(str(exc))
        except Exception as exc:
            logger.warning("背景图保存失败: %s", exc, exc_info=True)
            return await _fail(f"背景图保存失败: {exc}")
        logger.info("背景图上传成功: name=%s size=%s", filename, len(content))
        return await _ok(result)

    async def _read_upload(self, upload: Any) -> bytes:
        """读取上传文件字节：优先 read 接口，退化时落盘临时文件再读（不残留）。"""
        read_fn = getattr(upload, "read", None)
        if callable(read_fn):
            value = read_fn()
            data = await value if inspect.isawaitable(value) else value
            if isinstance(data, (bytes, bytearray)):
                return bytes(data)
        bg_dir = self._plugin.data_dir / "backgrounds"
        bg_dir.mkdir(parents=True, exist_ok=True)
        tmp = bg_dir / ".upload_tmp"
        await _save_upload(upload, tmp)
        content = tmp.read_bytes()
        try:
            tmp.unlink()
        except OSError:
            pass
        return content

    async def appearance_background_select(self) -> Any:
        body = await _json_body(default={})
        bg_hash = str(body.get("hash") or "")[:32] if isinstance(body, dict) else ""
        if not bg_hash:
            return await _fail("缺少 hash 参数")
        logger.info("切换背景图: hash=%s", bg_hash)
        try:
            result = self._plugin.appearance.select_background(bg_hash)
        except ValueError as exc:
            return await _fail(str(exc))
        return await _ok(result)

    async def appearance_background_clear(self) -> Any:
        logger.info("清除背景图")
        result = self._plugin.appearance.clear_background()
        return await _ok(result)

    # ------------------------------------------------------------- 风格锚

    async def voice_read(self) -> Any:
        return await _ok({"voice": self._plugin.voice_store.load()})

    async def voice_update(self) -> Any:
        body = await _json_body(default={})
        if not isinstance(body, dict):
            return await _fail("请求体必须是 JSON 对象")
        voice = self._plugin.voice_store.save(body)
        return await _ok({"voice": voice})

    async def voice_generate(self) -> Any:
        body = await _json_body(default={})
        persona_desc = str((body or {}).get("persona_desc") or "").strip()
        if not persona_desc:
            return await _fail("缺少人格描述")
        try:
            from .models import resolve_chat_provider as _res_vgen

            provider, provider_id = _res_vgen(self._plugin.context, self._plugin.config, "voice_gen")
            if provider is None:
                return await _fail("风格生成模型未配置（请在风格页选择生成模型，或配置「留空回退模型」）")
            prompt = build_generate_prompt(persona_desc)
            resp = await chat_text(
                provider, self._plugin.config, prompt=prompt, session_id="storyteller_voice_generate",
                _disable_thinking=False,  # 风格档案属创作：保留模型思考
            )
            self._plugin._record_usage(resp, "voice_gen", provider_id or "default")
            text = str(getattr(resp, "completion_text", "") or "")
            voice = parse_generated_voice(text)
            if not isinstance(voice, dict):
                return await _fail("生成结果无法解析为风格档案，请重试")
            saved = self._plugin.voice_store.save(voice)
            return await _ok({"voice": saved, "raw": text[:2000]})
        except Exception as exc:
            logger.warning("[Storyteller] 一键生成风格失败: %s", exc)
            return await _fail("一键生成失败")

    async def voice_personas(self) -> Any:
        """读取 AstrBot 人格库（personas_v3 列表/候选接口），供一键生成前选择人格标题并填充其 prompt。

        - 优先枚举人格库：manager.personas_v3 或 get_personas/list_personas/all_personas/get_persona_list；
        - 每项取「人格标题（name/title）」显示，选中后把其 prompt 填入输入框；
        - 取不到库时兜底当前默认人格（get_default_persona_v3）。
        """
        try:
            manager = getattr(self._plugin.context, "persona_manager", None)
            if manager is None:
                return await _ok({"personas": []})
            pv = getattr(manager, "personas_v3", None)
            if not (isinstance(pv, (list, tuple)) and len(pv) > 0):
                pv = None
                for meth in ("get_personas", "list_personas", "all_personas", "get_persona_list"):
                    fn = getattr(manager, meth, None)
                    if not callable(fn):
                        continue
                    try:
                        res = fn()
                    except TypeError:
                        continue
                    try:
                        from inspect import isawaitable

                        if isawaitable(res):
                            import asyncio as _a

                            res = await _a.wait_for(res, timeout=2.0)
                    except Exception:
                        res = None
                    if isinstance(res, (list, tuple)) and len(res) > 0:
                        pv = res
                        break
            out = []
            if isinstance(pv, (list, tuple)) and len(pv) > 0:
                for idx, item in enumerate(pv):
                    name = ""
                    prompt = ""
                    if isinstance(item, dict):
                        name = str(item.get("name") or item.get("title") or "").strip()[:80]
                        prompt = str(item.get("prompt") or item.get("system_prompt") or item.get("content") or "").strip()
                    else:
                        for attr in ("name", "title"):
                            try:
                                v = getattr(item, attr, None)
                            except Exception:
                                v = None
                            if v:
                                name = str(v).strip()[:80]
                                break
                        for attr in ("prompt", "system_prompt", "content"):
                            try:
                                v = getattr(item, attr, None)
                            except Exception:
                                v = None
                            if v:
                                prompt = str(v).strip()
                                break
                    if not name:
                        try:
                            name = str(getattr(item, "id", "") or (item.get("id") if isinstance(item, dict) else ""))
                        except Exception:
                            name = ""
                        name = name or f"人格 {idx + 1}"
                    if prompt:
                        out.append({"persona_id": name[:80], "name": name[:40], "description": prompt[:2000]})
            if not out:
                getter = getattr(manager, "get_default_persona_v3", None)
                if callable(getter):
                    try:
                        result = getter(umo="")
                    except TypeError:
                        try:
                            result = getter()
                        except TypeError:
                            result = None
                    try:
                        from inspect import isawaitable

                        if isawaitable(result):
                            import asyncio as _a

                            result = await _a.wait_for(result, timeout=2.0)
                    except Exception:
                        result = None
                    prompt = ""
                    if isinstance(result, dict):
                        prompt = str(result.get("prompt") or result.get("system_prompt") or result.get("content") or "")
                    elif isinstance(result, str):
                        prompt = result
                    elif result is not None:
                        for attr in ("prompt", "system_prompt", "content"):
                            try:
                                v = getattr(result, attr, None)
                            except Exception:
                                v = None
                            if v:
                                prompt = str(v)
                                break
                    prompt = (prompt or "").strip()
                    if prompt:
                        out = [{"persona_id": "astrbot_default", "name": "AstrBot 默认人格", "description": prompt[:2000]}]
            return await _ok({"personas": out})
        except Exception:
            return await _ok({"personas": []})

    async def persona_read(self) -> Any:
        return await _ok({"persona": self._plugin.persona_store.load()})

    async def persona_update(self) -> Any:
        body = await _json_body(default={})
        text = str((body or {}).get("text") or "").strip()
        saved = self._plugin.persona_store.save(text)
        return await _ok({"persona": saved})

    async def persona_generate(self) -> Any:
        """按人格描述一键生成「人格注入体」（直连 persona 生成模型，自动保存）。"""
        body = await _json_body(default={})
        persona_desc = str((body or {}).get("persona_desc") or "").strip()
        if not persona_desc:
            return await _fail("缺少人格描述")
        try:
            from .models import resolve_chat_provider as _res_pgen
            from .persona_profile import build_persona_generate_prompt

            provider, provider_id = _res_pgen(self._plugin.context, self._plugin.config, "persona_gen")
            if provider is None:
                return await _fail("人格生成模型未配置（请在人格页选择生成模型，或配置「留空回退模型」）")
            prompt = build_persona_generate_prompt(persona_desc)
            resp = await chat_text(
                provider, self._plugin.config, prompt=prompt, session_id="storyteller_persona_generate",
                _disable_thinking=False,  # 人格注入体属创作：保留模型思考
            )
            self._plugin._record_usage(resp, "persona_gen", provider_id or "default")
            text = str(getattr(resp, "completion_text", "") or "").strip()
            if not text:
                return await _fail("生成结果为空，请重试")
            saved = self._plugin.persona_store.save(text)
            return await _ok({"persona": saved})
        except Exception as exc:
            logger.warning("[Storyteller] 一键生成人格注入体失败: %s", exc)
            return await _fail("一键生成失败")

    async def voice_examples(self) -> Any:
        return await _ok({"examples": VOICE_EXAMPLES})

    # ------------------------------------------------------------- 状态锚

    async def presence_read(self) -> Any:
        presence = self._plugin.presence_store.load()
        import time as _time

        from .presence import compose_stance

        schedule = self._plugin.schedule_store.load()
        stance = compose_stance(
            presence,
            schedule if self._plugin.config.bool("schedule.enabled", True) else None,
            _time.strftime("%Y-%m-%d %H:%M", _time.localtime()),
        )
        return await _ok(
            {
                "presence": presence,
                "diagnostic": {
                    "auto_refresh": self._plugin.config.bool("presence.auto_refresh", False),
                    "updated_at": presence.get("updated_at", ""),
                    "source": presence.get("source", ""),
                    "now": _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime()),
                    "stance": stance,
                    "next_beat_min": max(0, self._plugin.config.int("presence.beat_interval", 30)),
                },
            }
        )

    async def presence_update(self) -> Any:
        body = await _json_body(default={})
        if not isinstance(body, dict):
            return await _fail("请求体必须是 JSON 对象")
        presence = self._plugin.presence_store.save(body)
        return await _ok({"presence": presence})

    async def presence_evolve(self) -> Any:
        """手动一键演化（直连状态模型生成当前状态并保存）。"""
        try:
            await self._plugin._refresh_presence(manual=True)
        except Exception as exc:
            logger.warning("[Storyteller] 手动演化状态失败: %s", exc)
            return await _fail("演化失败")
        return await self.presence_read()

    async def presence_generate(self) -> Any:
        body = await _json_body(default={})
        try:
            provider = self._plugin.context.get_using_provider()
            if provider is None:
                return await _fail("当前会话没有可用的 LLM Provider")
            import time as _time

            now = _time.strftime("%Y-%m-%d %H:%M", _time.localtime())
            from .schedule import current_activity

            schedule = self._plugin.schedule_store.load()
            activity = current_activity(schedule, now[11:16])
            prompt = build_presence_generate_prompt(
                now=now, schedule=activity or "", memories="", context=""
            )
            resp = await chat_text(provider, self._plugin.config, prompt=prompt, session_id="storyteller_presence_generate")
            presence = parse_presence(str(getattr(resp, "completion_text", "") or ""))
            if not isinstance(presence, dict):
                return await _fail("生成结果无法解析，请重试")
            presence["source"] = "auto"
            saved = self._plugin.presence_store.save(presence)
            return await _ok({"presence": saved})
        except Exception as exc:
            logger.warning("[Storyteller] 一键生成状态失败: %s", exc)
            return await _fail("一键生成失败")

    # ------------------------------------------------------------- 日程锚

    async def rewrite_buffer(self) -> Any:
        """润色缓冲（发送给润色 LLM 的内容 / 润色后内容），实时面板用。"""
        limit = _query("limit", 20)
        try:
            n = max(1, min(200, int(limit)))
        except (TypeError, ValueError):
            n = 20
        polisher = getattr(self._plugin, "polisher", None)
        items = polisher.buffer.items(n) if polisher is not None else []
        return await _ok({"items": items})

    async def schedule_read(self) -> Any:
        schedule = self._plugin.schedule_store.load()
        import time as _time
        from .schedule import current_activity

        now = _time.strftime("%H:%M", _time.localtime())
        return await _ok(
            {
                "schedule": schedule,
                "diagnostic": {
                    "current_activity": current_activity(schedule, now),
                    "count": len(schedule.get("entries", [])),
                    "backlog_count": len(schedule.get("backlog", [])),
                    "future_count": len(schedule.get("future", [])),
                    "now": now,
                },
            }
        )

    async def schedule_update(self) -> Any:
        body = await _json_body(default={})
        items = body.get("entries") if isinstance(body, dict) else None
        schedule = self._plugin.schedule_store.save_entries(items)
        return await _ok({"schedule": schedule})

    async def schedule_generate(self) -> Any:
        """一键生成今天完整日程 + 穿搭（复用 main 的生成逻辑，覆盖当前日程）。"""
        try:
            logger.info("[Storyteller] 收到一键生成日程请求")
            result = await self._plugin._generate_schedule()
            if not result.get("ok"):
                return await _fail(f"生成失败：{result.get('error') or '未知原因'}")
            return await _ok(
                {
                    "schedule": self._plugin.schedule_store.load(),
                    "wardrobe": self._plugin.wardrobe_store.load(),
                }
            )
        except Exception as exc:
            logger.warning("[Storyteller] 一键生成日程失败: %s", exc)
            return await _fail(f"一键生成失败：{str(exc) or type(exc).__name__}")

    async def schedule_prompt_preview(self) -> Any:
        """预览「一键生成日程」实际发送给直连模型的完整提示词。

        只读拼装：复用与真实生成完全相同的构造器与素材来源，
        不调用 LLM、不消耗 Token；附带素材清单（哪些拼进去了/哪些为空）。
        """
        try:
            from .presence import build_presence_anchor
            from .schedule import build_schedule_generate_prompt

            voice = self._plugin.voice_store.load()
            persona_desc = str(voice.get("tone") or "")
            persona_injection = str(self._plugin.persona_store.injection_text() or "")
            weather = str(self._plugin.config.get("presence.weather", "") or "").strip()
            presence = build_presence_anchor(self._plugin.presence_store.load())
            memories = self._plugin._recent_memory_hint(limit=6)
            closet = self._plugin.wardrobe_store.closet_items()
            sched = self._plugin.schedule_store.load()
            future = sched.get("future")
            backlog = sched.get("backlog")
            prompt = build_schedule_generate_prompt(
                persona_desc=persona_desc,
                persona_injection=persona_injection,
                memories=memories,
                weather=weather,
                presence=presence,
                closet=closet,
                future=future,
                backlog=backlog,
                diary_time=str(self._plugin.config.get("schedule.diary_time", "23:30") or "23:30").strip()[:5],
                diary_minutes=max(5, min(60, self._plugin.config.int("schedule.diary_minutes", 20) or 20)),
            )
            # 模型展示：不触发 resolve（避免无谓报错日志），按「留空回退」策略算出实际生效的 id
            pid = str(self._plugin.config.get("schedule.provider_id", "") or "").strip()
            fallback_on = self._plugin.config.bool("models.fallback_enabled", True)
            fallback_id = str(self._plugin.config.get("models.fallback_provider_id", "") or "").strip()
            model_disp = pid or (fallback_id if fallback_on else "") or "（未配置，生成会被驳回）"

            def _ing(label: str, text: str, note: str) -> dict:
                t = str(text or "").strip()
                return {"label": label, "used": bool(t), "note": note, "preview": t[:80]}

            closet_names = "、".join(str(c.get("name") or "") for c in closet if isinstance(c, dict))
            future_text = "；".join(str(f.get("activity") or "") for f in (future or [])[:5] if isinstance(f, dict))
            backlog_text = "；".join(str(b.get("activity") or "") for b in (backlog or [])[:5] if isinstance(b, dict))
            ingredients = [
                {"label": "任务说明与输出格式", "used": True, "note": "固定模板：只输出一个 JSON 对象（entries=当天日程段、outfit=今日穿搭），按时间升序、具体像真人、输出精简", "preview": ""},
                _ing("人格与世界观（注入体）", persona_injection, "来自「人格」页注入体（persona_injection.json，含世界观设定），日程必须贴合"),
                _ing("人格/风格", persona_desc, "来自「风格」页档案的语气描述（voice.tone）"),
                _ing("此刻状态", presence, "当前心情/精力（状态模块锚）"),
                _ing("今天天气", weather, "来自「设置 → 状态」里的天气文本"),
                _ing("记忆里的约定/愿望/偏好", memories, "联动记忆插件最近 6 条（每条≤80 字）"),
                _ing("她的衣柜", closet_names, "现有衣物名单，穿搭必须从中选 2~5 件"),
                _ing("未来规划", future_text, "最多取 5 条，时间合适就排进今天"),
                _ing("延误事项", backlog_text, "最多取 5 条，今天有空就补上"),
            ]
            return await _ok(
                {
                    "prompt": prompt,
                    "model": model_disp,
                    "length": len(prompt),
                    "ingredients": ingredients,
                }
            )
        except Exception as exc:
            logger.warning("[Storyteller] 日程提示词预览失败: %s", exc)
            return await _fail(f"预览失败：{str(exc) or type(exc).__name__}")

    async def diag_runtime(self) -> Any:
        """运行时诊断：工作目录/数据目录/配置路径/各提供商运行时状态（Key 只显示尾号）。

        用途：排查"面板连通性 OK 但生成失败"类问题——面板测试与插件生成走的
        都是运行时 Provider（内存配置），与 cmd_config.json 文件可能不同步；
        这里展示的是进程内真实值。
        """
        out: dict = {"cwd": "", "data_dir": "", "config_path": "", "providers": []}
        try:
            import os as _os

            from astrbot.core.utils.astrbot_path import get_astrbot_data_path

            out["cwd"] = _os.getcwd()
            out["data_dir"] = get_astrbot_data_path()
            out["config_path"] = _os.path.join(get_astrbot_data_path(), "cmd_config.json")
            getter = getattr(self._plugin.context, "get_all_providers", None)
            if callable(getter):
                for p in (getter() or []):
                    try:
                        meta_id = str(getattr(p.meta(), "id", "") or "")
                    except Exception:
                        meta_id = ""
                    cfg = getattr(p, "provider_config", None) or {}
                    client = getattr(p, "client", None)
                    key = str(getattr(client, "api_key", "") or cfg.get("key", "") or "")
                    base = str(getattr(client, "base_url", "") or cfg.get("api_base", "") or "")
                    model = ""
                    try:
                        model = str(p.get_model() or "")
                    except Exception:
                        pass
                    out["providers"].append(
                        {
                            "id": meta_id,
                            "model": model,
                            "base": base,
                            "key_tail": key[-4:] if len(key) >= 4 else "",
                            "key_len": len(key),
                            "timeout": cfg.get("timeout"),
                        }
                    )
        except Exception:
            pass
        return await _ok(out)

    # ------------------------------------------------------------- 清障（模块自检）

    def _self_check_items(self) -> list[tuple[str, str, str, Any]]:
        """清障页只读自检项定义：(key, name, desc, fn)。执行零副作用（不调 LLM、不发消息、不写数据）。"""
        plugin = self._plugin
        items: list[tuple[str, str, str, Any]] = []

        def add(key: str, name: str, desc: str, fn: Any) -> None:
            items.append((key, name, desc, fn))

        def cfg_status() -> tuple[bool, str]:
            cfg = plugin.config
            for probe in (
                lambda: cfg.bool("intercept.enabled", True),
                lambda: cfg.int("debounce.window", 2),
                lambda: cfg.float("emoji.send_probability", 0.25),
                lambda: str(cfg.get("intercept.mode", "") or ""),
            ):
                probe()
            return True, "配置读取正常"

        def data_dir_status() -> tuple[bool, str]:
            import os

            d = str(getattr(plugin, "data_dir", "") or "")
            if not d or not os.path.isdir(d):
                return False, f"数据目录不存在：{d}"
            if not os.access(d, os.W_OK):
                return False, f"数据目录不可写：{d}"
            return True, d

        def token_store_status() -> tuple[bool, str]:
            store = getattr(plugin, "token_store", None)
            if store is None:
                return False, "Token 记账未初始化"
            s = store.stats()
            total = int(s.get("total", {}).get("sum", 0) or 0)
            return True, f"记账正常（累计 {total} tokens）"

        def ui_state_status() -> tuple[bool, str]:
            store = getattr(plugin, "ui_state", None) or getattr(plugin, "ui", None)
            if store is None:
                return False, "布局存储未初始化"
            return True, "选项卡布局存储正常"

        def appearance_status() -> tuple[bool, str]:
            store = getattr(plugin, "appearance_store", None) or getattr(plugin, "appearance", None)
            if store is None:
                return False, "外观存储未初始化"
            loader = getattr(store, "load", None)
            if callable(loader):
                try:
                    loader()
                except Exception as exc:
                    return False, f"外观数据读取失败：{str(exc)[:120]}"
            return True, "外观数据可读"

        def presence_status() -> tuple[bool, str]:
            store = getattr(plugin, "presence_store", None)
            if store is None:
                return False, "状态存储未初始化"
            store.load()
            return True, "状态数据可读"

        def schedule_status() -> tuple[bool, str]:
            store = getattr(plugin, "schedule_store", None)
            if store is None:
                return False, "日程存储未初始化"
            store.load()
            return True, "日程数据可读"

        def emoji_status() -> tuple[bool, str]:
            store = getattr(plugin, "emoji_store", None)
            if store is None:
                return False, "表情包图库未初始化"
            cats = store.categories()
            return True, f"图库可读（{len(cats)} 个分类）"

        def send_buffer_status() -> tuple[bool, str]:
            manager = getattr(plugin, "reply_buffer", None)
            if manager is None:
                return False, "发送缓冲未初始化"
            manager.status()
            return True, "发送缓冲就绪"

        def relationship_status() -> tuple[bool, str]:
            store = getattr(plugin, "relationship_store", None)
            if store is None:
                return False, "关系档案未初始化"
            try:
                store.all()
            except AttributeError:
                pass
            return True, "关系档案可读"

        def persona_voice_status() -> tuple[bool, str]:
            voice = getattr(plugin, "voice_store", None)
            persona = getattr(plugin, "persona_store", None)
            ok = True
            notes = []
            if voice is None:
                ok = False
                notes.append("风格档案未初始化")
            if persona is None:
                ok = False
                notes.append("人格注入体未初始化")
            return ok, ("；".join(notes) if notes else "风格与人格档案可读")

        def mind_status() -> tuple[bool, str]:
            store = getattr(plugin, "mind_store", None)
            if store is None:
                return False, "内心世界存储未初始化"
            store.all()
            return True, "内心数据可读"

        def memory_bridge_status() -> tuple[bool, str]:
            getter = getattr(plugin, "_memory_bridge_status", None)
            status = getter() if callable(getter) else {}
            if not status:
                return False, "联动状态不可用"
            if not status.get("available"):
                return False, str(status.get("reason") or "联动不可用")
            return True, f"联动正常（{str(status.get('dm_version') or status.get('version') or '')}）".strip()

        def models_status() -> tuple[bool, str]:
            from .models import configured_id, fallback_enabled

            cfg = plugin.config
            any_configured = False
            for fn in ("rewrite", "judge", "takeover", "schedule", "presence", "proactive", "dream"):
                if configured_id(cfg, fn):
                    any_configured = True
                    break
            fallback = str(cfg.get("models.fallback_provider_id", "") or "").strip()
            if any_configured or fallback:
                return True, "模型路由可用（回退策略在位）"
            if not fallback_enabled(cfg):
                return False, "「留空回退模型」已关闭且各功能均未配置模型——所有生成请求都会被驳回"
            return False, "回退模型为空、各功能也未配置模型——所有生成请求都会被驳回"

        def bg_tasks_status() -> tuple[bool, str]:
            alive: list[str] = []
            # 常驻后台循环（真实属性名：_mind_task；兼容其它命名）
            for attr in ("_mind_task", "_mind_loop_task", "_proactive_loop_task"):
                task = getattr(plugin, attr, None)
                if task is not None and callable(getattr(task, "done", None)) and not task.done():
                    alive.append(attr)
            # 主动管理器内部循环（proactive manager 的属性名因版本而异，防御探测）
            manager = getattr(plugin, "proactive", None)
            if manager is not None:
                for attr in ("loop_task", "_loop_task", "_proactive_task"):
                    mgr_task = getattr(manager, attr, None)
                    if mgr_task is not None and callable(getattr(mgr_task, "done", None)) and not mgr_task.done():
                        alive.append("proactive_loop")
                        break
            if not alive:
                return False, "未发现运行中的后台任务（内心循环未启动或被停止）"
            names = {
                "_mind_task": "内心循环", "_mind_loop_task": "内心循环",
                "_proactive_loop_task": "主动循环", "proactive_loop": "主动循环",
            }
            return True, "后台任务运行中（" + "、".join(names.get(a, a) for a in alive) + "）"

        def logger_status() -> tuple[bool, str]:
            from .log import get_logger

            get_logger("清障")
            return True, "日志系统正常"

        add("config", "配置加载", "插件配置对象可正常读取布尔/数值/文本键", cfg_status)
        add("data_dir", "数据目录", "插件数据目录存在且可写", data_dir_status)
        add("token_store", "Token 记账", "token.json 记账与统计可读", token_store_status)
        add("ui_state", "界面布局", "选项卡布局存储可读", ui_state_status)
        add("appearance", "外观", "外观主题与背景数据可读", appearance_status)
        add("presence", "状态", "心情/精力数据可读", presence_status)
        add("schedule", "日程", "日程与未来规划数据可读", schedule_status)
        add("emoji", "表情包", "图库分类可读（图片文件数）", emoji_status)
        add("send_buffer", "发送缓冲", "发送缓冲管理器就绪", send_buffer_status)
        add("relationship", "关系", "关系档案数据可读", relationship_status)
        add("persona_voice", "风格 · 人格", "风格档案与人格注入体可读", persona_voice_status)
        add("mind", "内心世界", "梦境/思考/见闻数据可读", mind_status)
        add("memory_bridge", "记忆联动", "与【为你篆刻的历史】的桥接可用", memory_bridge_status)
        add("models", "模型配置", "至少一个功能模型或回退模型在位", models_status)
        add("bg_tasks", "后台任务", "定时循环（内心/关系/画像/主动）存活", bg_tasks_status)
        add("logger", "日志系统", "插件日志可写", logger_status)
        return items

    def _run_self_checks(self, keys: list[str] | None = None) -> list[dict]:
        """执行只读自检项；key 过滤可单跑。"""
        results: list[dict] = []
        for key, name, desc, fn in self._self_check_items():
            if keys is not None and key not in keys:
                continue
            try:
                ok, detail = fn()
                results.append({
                    "key": key, "name": name, "desc": desc, "kind": "internal",
                    "ok": bool(ok), "detail": str(detail or "")[:200],
                })
            except Exception as exc:
                results.append({
                    "key": key, "name": name, "desc": desc, "kind": "internal",
                    "ok": False, "detail": f"自检抛出异常：{str(exc)[:160]}",
                })
        return results

    def _self_check_definitions(self) -> list[dict]:
        """全部自检项定义（不含结果）：内部 16 项 + LLM 15 项（14 模块 + 回退）+ 下游客户端。"""
        defs = [{"key": k, "name": n, "desc": d, "kind": "internal"}
                for k, n, d, _fn in self._self_check_items()]
        for module_key, module_name, _func_keys in self._LLM_MODULE_SPECS:
            defs.append({
                "key": f"llm_{module_key}", "name": f"{module_name} · LLM",
                "desc": f"「{module_name}」模块配置模型的真实生成链路（极小提示词，少量消耗）",
                "kind": "llm",
            })
        defs.append({
            "key": "llm_fallback", "name": "回退模型 · LLM",
            "desc": "「留空回退模型」的真实生成链路（极小提示词，少量消耗）",
            "kind": "llm",
        })
        defs.append({
            "key": "llm_embedding", "name": "记忆 · 嵌入模型",
            "desc": "记忆嵌入模型连通性（真实嵌入一次短文，少量消耗；未配置即报错）",
            "kind": "llm",
        })
        defs.append({
            "key": "platforms", "name": "下游客户端",
            "desc": "消息平台适配器连接状态（OneBot 等真实连接检测）",
            "kind": "client",
        })
        return defs

    async def _ping_llm(self, provider: Any, timeout: float) -> dict:
        """真实 LLM 可达性：发一个极短提示词验证生成链路（少量 token，按超时控制）。

        返回 {ok, elapsed_ms, error}；单次限时（超时即失败），不重试。
        """
        started = time.monotonic()
        try:
            prompt = "请只回复：OK"
            stream_method = getattr(provider, "text_chat_stream", None)
            if callable(stream_method):
                async def _consume_stream() -> str:
                    got = ""
                    async for chunk in stream_method(prompt=prompt, session_id="storyteller_diag_ping", persist=False):
                        text = str(getattr(chunk, "completion_text", "") or "")
                        if text:
                            got = text
                    return got

                try:
                    got = await asyncio.wait_for(_consume_stream(), timeout=timeout)
                except asyncio.TimeoutError:
                    return {"ok": False, "elapsed_ms": int((time.monotonic() - started) * 1000), "error": f"超时（{timeout}s）"}
                if got.strip():
                    return {"ok": True, "elapsed_ms": int((time.monotonic() - started) * 1000), "error": ""}
                return {"ok": False, "elapsed_ms": int((time.monotonic() - started) * 1000), "error": "流式调用无输出"}
            method = getattr(provider, "text_chat", None)
            if not callable(method):
                method = getattr(provider, "text", None)
            if not callable(method):
                return {"ok": False, "elapsed_ms": int((time.monotonic() - started) * 1000), "error": "Provider 不支持 text_chat/text"}
            resp = await asyncio.wait_for(
                method(prompt=prompt, session_id="storyteller_diag_ping", persist=False),
                timeout=timeout,
            )
            text = str(getattr(resp, "completion_text", "") or "")
            if text.strip():
                return {"ok": True, "elapsed_ms": int((time.monotonic() - started) * 1000), "error": ""}
            return {"ok": False, "elapsed_ms": int((time.monotonic() - started) * 1000), "error": "调用无输出"}
        except asyncio.TimeoutError:
            return {"ok": False, "elapsed_ms": int((time.monotonic() - started) * 1000), "error": f"超时（{timeout}s）"}
        except Exception as exc:
            return {"ok": False, "elapsed_ms": int((time.monotonic() - started) * 1000), "error": str(exc)[:160]}

    @staticmethod
    def _onebot_connection_state(platform: Any) -> int | None:
        """aiocqhttp（OneBot v11）平台的连接级检测：反向 WS 客户端集合。

        CQHttp 的 _wsr_api_clients / _wsr_event_clients 在连接建立时写入、断开时移除
        （实锤 aiocqhttp 源码：del _wsr_api_clients[self_id] / _wsr_event_clients.discard）——
        非空 = OneBot（NapCat 等）已连接；空 = 未连接。其它平台无此机制返回 None。
        """
        try:
            getter = getattr(platform, "get_client", None)
            if not callable(getter):
                return None
            bot = getter()
            api = getattr(bot, "_wsr_api_clients", None)
            evt = getattr(bot, "_wsr_event_clients", None)
            count = 0
            if isinstance(api, dict):
                count += len(api)
            elif isinstance(api, (set, list)):
                count += len(api)
            if isinstance(evt, (set, list)):
                count += len(evt)
            if hasattr(bot, "_wsr_api_clients") or hasattr(bot, "_wsr_event_clients"):
                return count
            return None
        except Exception:
            return None

    async def _check_platforms(self) -> dict:
        """下游客户端检查：适配器状态 + 连接级检测（OneBot 反向连接）。

        说明：AstrBot 的 Platform.status 只表示适配器生命周期（启动/错误），
        不代表下游（NapCat 等）是否连上；本检查对 aiocqhttp 平台读 CQHttp 的
        实时连接集合判定真连接，其它平台退化为状态说明。
        """
        base = {"key": "platforms", "name": "下游客户端", "desc": "消息平台适配器连接状态（OneBot 等真实连接检测）"}
        try:
            ctx = getattr(self._plugin, "context", None)
            manager = getattr(ctx, "platform_manager", None) if ctx is not None else None
            if manager is None:
                return {**base, "ok": False, "detail": "平台管理器不可用（AstrBot 未提供 platform_manager）"}
            insts = list(getattr(manager, "platform_insts", None) or [])
            if not insts:
                return {**base, "ok": False, "detail": "未发现已加载的消息平台适配器"}
            lines: list[str] = []
            ok_all = True
            for pl in insts:
                try:
                    stats_getter = getattr(pl, "get_stats", None)
                    stats = stats_getter() if callable(stats_getter) else {}
                    pname = str(stats.get("display_name") or stats.get("type") or "未知平台")
                    status = str(stats.get("status") or "unknown")
                    if status == "running":
                        conn = self._onebot_connection_state(pl)
                        if conn is None:
                            lines.append(f"{pname} 已启动（无连接级指标）")
                        elif conn > 0:
                            lines.append(f"{pname} 已连接（{conn} 个 OneBot 客户端）")
                        else:
                            ok_all = False
                            lines.append(f"{pname} 已启动但未检测到 OneBot 连接（NapCat 等未连接）")
                    else:
                        ok_all = False
                        err = ""
                        last = stats.get("last_error") or {}
                        if isinstance(last, dict) and last.get("message"):
                            err = str(last["message"])[:100]
                        err_count = int(stats.get("error_count") or 0)
                        lines.append(f"{pname} 状态 {status}" + (f"（错误 {err_count} 次" + (f"：{err}" if err else "") + "）"))
                except Exception as exc:
                    ok_all = False
                    lines.append(f"平台状态读取异常：{str(exc)[:80]}")
            if ok_all:
                return {**base, "ok": True, "detail": "；".join(lines)}
            return {**base, "ok": False, "detail": ("；".join(lines))[:200]}
        except Exception as exc:
            return {**base, "ok": False, "detail": f"客户端检查异常：{str(exc)[:120]}"}

    # 各模块的功能键与配置键（模块级 LLM 可达性检查用）
    _LLM_MODULE_SPECS: list[tuple[str, str, list[tuple[str, str]]]] = [
        ("presence", "状态", [("presence", "presence.provider_id")]),
        ("schedule", "日程", [("schedule", "schedule.provider_id")]),
        ("mind", "内心", [
            ("dream", "mind.dream_provider_id"), ("think", "mind.think_provider_id"),
            ("diary", "mind.diary_provider_id"), ("search", "search.provider_id"),
        ]),
        ("proactive", "主动", [("proactive", "proactive.provider_id")]),
        ("relationship", "关系", [("judge", "pipeline.provider_id")]),
        ("debounce", "防抖", [("smart_judge", "debounce.smart_provider_id")]),
        ("intercept", "拦＆改", [("takeover", "intercept.provider_id")]),
        ("rewrite", "润色", [("rewrite", "rewrite.provider_id")]),
        ("emoji", "表情包", [("emoji_judge", "emoji.judge_provider_id")]),
        ("send", "发送", [("interrupt", "send.interrupt_judge_provider_id")]),
        ("memory", "记忆", [
            ("profile", "memory.profile_provider_id"), ("commitment", "memory.commitment_provider_id"),
        ]),
        ("voice", "风格", [("voice_gen", "voice.provider_id")]),
        ("persona", "人格", [("persona_gen", "persona.provider_id")]),
        ("wardrobe", "穿搭", [("wardrobe_gen", "wardrobe.provider_id")]),
    ]

    def _provider_by_id(self, provider_id: str) -> Any | None:
        """按 id 取 provider 实例（防御读取）。"""
        try:
            ctx = getattr(self._plugin, "context", None)
            getter = getattr(ctx, "get_provider_by_id", None)
            if callable(getter):
                return getter(provider_id)
        except Exception:
            return None
        return None

    async def _module_llm_results(self, module_key: str, module_name: str, timeout: float) -> dict:
        """对某模块做真实 LLM 测试：逐个功能键的模型依次 ping；都未配置时测回退模型。"""
        base = {"key": f"llm_{module_key}", "name": f"{module_name} · LLM", "kind": "llm"}
        from .models import configured_id

        cfg = getattr(self._plugin, "config", None)
        lines: list[str] = []
        ok_all = True
        spec = next((s for s in self._LLM_MODULE_SPECS if s[0] == module_key), None)
        func_keys: list[tuple[str, str]] = spec[2] if spec else []
        targets: list[tuple[str, str, Any | None]] = []
        for fn, cfg_key in func_keys:
            pid = configured_id(cfg, fn) if cfg is not None else ""
            provider = self._provider_by_id(pid) if pid else None
            targets.append((fn, pid, provider))
        any_configured = any(pid for _fn, pid, _p in targets)
        if not any_configured:
            fallback_id = str(cfg.get("models.fallback_provider_id", "") or "").strip() if cfg is not None else ""
            provider = self._provider_by_id(fallback_id) if fallback_id else None
            if provider is not None:
                r = await self._ping_llm(provider, timeout)
                label = self._provider_label(provider, fallback_id)
                if r["ok"]:
                    lines.append(f"回退模型 {label}：OK（{r['elapsed_ms']}ms）")
                else:
                    ok_all = False
                    lines.append(f"回退模型 {label}：{r['error']}")
            else:
                ok_all = False
                lines.append("未配置专属模型且回退模型未配置——本模块生成会被驳回")
            return {**base, "ok": ok_all, "detail": "；".join(lines)}
        for fn, pid, provider in targets:
            if not pid:
                continue
            if provider is None:
                ok_all = False
                lines.append(f"{fn}：模型 {pid} 在运行时不匹配（配置失效）")
                continue
            r = await self._ping_llm(provider, timeout)
            label = self._provider_label(provider, pid)
            if r["ok"]:
                lines.append(f"{fn} {label}：OK（{r['elapsed_ms']}ms）")
            else:
                ok_all = False
                lines.append(f"{fn} {label}：{r['error']}")
        return {**base, "ok": ok_all, "detail": ("；".join(lines))[:400]}

    def _provider_label(self, provider: Any, provider_id: str) -> str:
        try:
            model = str(provider.get_model() or "")
        except Exception:
            model = ""
        return f"{provider_id}（{model}）" if model else provider_id

    async def _ping_embedding(self, provider: Any, timeout: float) -> dict:
        """真实嵌入连通性：对短文本做一次 get_embedding（少量消耗，按超时控制）。"""
        started = time.monotonic()
        try:
            method = getattr(provider, "get_embedding", None)
            if not callable(method):
                return {"ok": False, "elapsed_ms": int((time.monotonic() - started) * 1000),
                        "error": "该 Provider 不支持 get_embedding 接口"}
            vec = await asyncio.wait_for(method("记忆测试"), timeout=timeout)
            dims = len(vec) if vec else 0
            if dims <= 0:
                return {"ok": False, "elapsed_ms": int((time.monotonic() - started) * 1000),
                        "error": "嵌入返回空向量"}
            return {"ok": True, "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "error": "", "dims": dims}
        except asyncio.TimeoutError:
            return {"ok": False, "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "error": f"超时（{timeout}s）"}
        except Exception as exc:
            return {"ok": False, "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "error": str(exc)[:160]}

    async def _embedding_llm_result(self, timeout: float) -> dict:
        """「记忆 · 嵌入模型」：真实嵌入连通性（严格模式：未配置即报错，不自动挑选）。"""
        base = {"key": "llm_embedding", "name": "记忆 · 嵌入模型", "kind": "llm"}
        from .models import configured_id

        cfg = getattr(self._plugin, "config", None)
        pid = configured_id(cfg, "embedding") if cfg is not None else ""
        if not pid:
            return {**base, "ok": False,
                    "detail": "嵌入模型未配置（嵌入不走「留空回退模型」；请到记忆页选择嵌入分类下的模型）"}
        provider = self._provider_by_id(pid)
        if provider is None:
            return {**base, "ok": False, "detail": f"嵌入模型 {pid} 在运行时不匹配（配置失效）"}
        r = await self._ping_embedding(provider, timeout)
        label = self._provider_label(provider, pid)
        if r.get("ok"):
            return {**base, "ok": True, "detail": f"{label}：OK（{r['elapsed_ms']}ms，维度 {r.get('dims')}）"}
        return {**base, "ok": False, "detail": f"{label}：{r.get('error', '失败')}"}

    async def _run_llm_ping(self, keys: list[str] | None = None, timeout: float | None = None) -> list[dict]:
        """依次（串行）真实 LLM 测试全部（或指定）模块 + 回退模型 + 嵌入模型。"""
        if timeout is None or timeout <= 0:
            timeout = 15.0
            try:
                cfg = getattr(self._plugin, "config", None)
                if cfg is not None:
                    timeout = float(max(5, int(cfg.int("troubleshoot.llm_test_timeout", 15) or 15)))
            except Exception:
                timeout = 15.0
        results: list[dict] = []
        if keys is None or any(k == "llm_fallback" for k in keys):
            fallback_id = ""
            cfg = getattr(self._plugin, "config", None)
            if cfg is not None:
                fallback_id = str(cfg.get("models.fallback_provider_id", "") or "").strip()
            base = {"key": "llm_fallback", "name": "回退模型 · LLM", "kind": "llm"}
            provider = self._provider_by_id(fallback_id) if fallback_id else None
            if provider is None:
                unbound = []
                if cfg is not None:
                    from .models import configured_id

                    for _mk, _mn, func_keys in self._LLM_MODULE_SPECS:
                        for fn, _ck in func_keys:
                            if not configured_id(cfg, fn) and fn not in unbound:
                                unbound.append(fn)
                if unbound:
                    results.append({**base, "ok": False,
                                    "detail": f"回退模型未配置，且以下功能未配专属模型（生成会被驳回）：{'、'.join(unbound[:8])}"})
                else:
                    results.append({**base, "ok": True, "detail": "未配置回退模型（各功能均有专属模型，无影响）"})
            else:
                r = await self._ping_llm(provider, timeout)
                label = self._provider_label(provider, fallback_id)
                if r["ok"]:
                    results.append({**base, "ok": True, "detail": f"{label}：OK（{r['elapsed_ms']}ms）"})
                else:
                    results.append({**base, "ok": False, "detail": f"{label}：{r['error']}"})
        for module_key, module_name, _func_keys in self._LLM_MODULE_SPECS:
            if keys is not None and f"llm_{module_key}" not in keys:
                continue
            results.append(await self._module_llm_results(module_key, module_name, timeout))
        if keys is None or "llm_embedding" in keys:
            results.append(await self._embedding_llm_result(timeout))
        return results

    async def diag_checks(self) -> Any:
        """清障页：全部自检项定义（不含结果；LLM 项默认不测，由用户点击触发）。"""
        return await _ok({"checks": self._self_check_definitions()})

    async def diag_check(self) -> Any:
        """清障页：单跑一项（body: {key}）。LLM 项为真实最小对话 ping（依次）。"""
        body = await _json_body(default={})
        key = str((body or {}).get("key") or "").strip()
        if not key:
            return await _fail("缺少 key")
        if key.startswith("llm_"):
            result = await self._run_llm_ping(keys=[key])
            if not result:
                return await _fail(f"未知的检查项: {key}")
            return await _ok({"check": result[0]})
        if key == "platforms":
            return await _ok({"check": await self._check_platforms()})
        results = self._run_self_checks(keys=[key])
        if not results:
            return await _fail(f"未知的检查项: {key}")
        return await _ok({"check": results[0]})

    async def diag_run(self) -> Any:
        """一键只读测试：内部 16 项 + 下游客户端（不含 LLM——LLM 由「一键 LLM 测试」另行触发）。"""
        results = self._run_self_checks()
        results.append(await self._check_platforms())
        return await _ok({"checks": results})

    async def diag_llm_test(self) -> Any:
        """一键 LLM 测试：依次（串行，非并发）真实 ping 全部（或指定）模块模型。

        body: {key?: str, timeout?: number}——key 指定时只测该模块/回退；timeout 覆盖页内设置。
        """
        body = await _json_body(default={})
        key = str((body or {}).get("key") or "").strip()
        timeout_raw = (body or {}).get("timeout")
        timeout = None
        try:
            timeout = float(timeout_raw) if timeout_raw not in (None, "") else None
        except (TypeError, ValueError):
            timeout = None
        if key:
            results = await self._run_llm_ping(keys=[key], timeout=timeout)
            if not results:
                return await _fail(f"未知的 LLM 检查项: {key}")
        else:
            results = await self._run_llm_ping(timeout=timeout)
        return await _ok({"checks": results})

    # ------------------------------------------------------------- 鸣谢

    async def thanks_images(self) -> Any:
        """返回特别鸣谢头像图片（data URL，避免受限 iframe 静态资源加载问题）。"""
        import base64
        import mimetypes

        images: dict[str, str] = {}
        root = Path(__file__).resolve().parent / "Special_Thanks"
        try:
            for name in ("DS", "QED", "SO2"):
                for ext in ("png", "jpg", "jpeg", "gif", "webp"):
                    path = root / f"{name}.{ext}"
                    if path.exists():
                        raw = path.read_bytes()
                        mime = mimetypes.guess_type(path.name)[0] or "image/png"
                        images[name] = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
                        break
        except Exception as exc:
            logger.warning("[Storyteller] 读取特别鸣谢头像失败: %s", exc)
        return await _ok({"images": images})

    # ------------------------------------------------------------- 主动对话

    async def proactive_status(self) -> Any:
        import time as _time

        manager = self._plugin.proactive
        last_sent = manager._last_sent
        now = _time.time()
        min_interval = max(1.0, self._plugin.config.float("proactive.min_interval_hours", 4.0)) * 3600
        max_interval = max(min_interval, self._plugin.config.float("proactive.max_interval_hours", 8.0)) * 3600
        sent_info = {}
        today_str = _time.strftime("%Y-%m-%d", _time.localtime())
        for user in manager.target_users():
            last = last_sent.get(user)
            uview = manager.user_state_view(user) if hasattr(manager, "user_state_view") else {}
            temp = manager._temperature(user) if hasattr(manager, "_temperature") else {}
            info = {
                "last_sent": None,
                "seconds_ago": 0,
                "ready_in_seconds": 0,
                "today_sent": manager._daily_per_user.get(user, 0),
                "last_interaction": None,
                "streak": uview.get("streak", 0),
                "silenced": bool(uview.get("silenced")),
                "temperature": temp.get("label", "普通"),
                "temperature_detail": temp.get("detail", ""),
            }
            if last:
                info["last_sent"] = _time.strftime("%H:%M:%S", _time.localtime(last))
                info["seconds_ago"] = int(now - last)
                info["ready_in_seconds"] = max(0, int(min_interval - (now - last)))
            li = manager._last_interaction.get(user)
            if li:
                info["last_interaction"] = _time.strftime("%H:%M:%S", _time.localtime(li))
            sent_info[user] = info
        # 0.176：已连接平台列表（主动页「消息平台前缀」下拉数据源 + 发送失败诊断）
        connected_platforms = getattr(manager, "_connected_platforms", None)
        platforms = connected_platforms() if callable(connected_platforms) else []
        return await _ok(
            {
                "enabled": manager.enabled(),
                "target_users": manager.target_users(),
                "daily_count": manager._daily_count.get(today_str, 0),
                "loop_running": manager._loop_task is not None and not manager._loop_task.done(),
                "min_interval_hours": self._plugin.config.float("proactive.min_interval_hours", 4.0),
                "max_interval_hours": self._plugin.config.float("proactive.max_interval_hours", 8.0),
                "quiet_hours": str(self._plugin.config.get("proactive.quiet_hours", "23:00-08:30") or "").strip(),
                "quiet_now": manager._in_quiet_hours(str(self._plugin.config.get("proactive.quiet_hours", "23:00-08:30") or "").strip()) if manager else False,
                "max_daily": max(0, self._plugin.config.int("proactive.max_daily", 3)),
                "per_user": sent_info,
                "candidates": manager.candidates(),
                "sent_history": manager.sent_history(),
                "connected_platforms": platforms,
            }
        )

    async def proactive_targets(self) -> Any:
        """管理主动目标用户：add 添加 / remove 删除（写 proactive.target_users 配置）。"""
        body = await _json_body(default={})
        action = str((body or {}).get("action") or "")
        tid = str((body or {}).get("id") or "").strip()
        if action not in ("add", "remove") or not tid:
            return await _fail("参数错误：action=add|remove + id")
        try:
            raw = str(self._plugin.config.get("proactive.target_users", "") or "")
            users = [u for u in raw.replace(",", " ").split() if u]
            if action == "add":
                if tid not in users:
                    users.append(tid)
            else:
                users = [u for u in users if u != tid]
            new_val = " ".join(users)
            raw_cfg = self._read_config_file()
            raw_cfg.setdefault("proactive", {})["target_users"] = new_val
            path = self._config_file_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(raw_cfg, ensure_ascii=False, indent=2), encoding="utf-8-sig")
            self._plugin.raw_config = raw_cfg
            self._plugin.config = ConfigView(raw_cfg)
            return await _ok({"users": users})
        except Exception as exc:
            logger.warning("[Storyteller] 目标用户管理失败: %s", exc)
            return await _fail(f"操作失败：{str(exc) or type(exc).__name__}")

    async def proactive_preview(self) -> Any:
        """试发预览：生成一条主动消息，不发送；返回判定原因+素材+正文。"""
        body = await _json_body(default={})
        user = str((body or {}).get("user") or "").strip()
        manager = self._plugin.proactive
        if not user:
            users = manager.target_users()
            if not users:
                return await _fail("未配置目标用户")
            user = users[0]
        try:
            from .inspiration import daypart_bucket

            ok, reason = manager._should_send(user, bucket=daypart_bucket(), cand=None)
            context = await manager._collect_context(user)
            text = await manager._generate(user, context)
            sources = {
                "mood": context.get("mood") or "",
                "activity": context.get("activity") or "",
                "memory": context.get("memory") or "",
                "timeline": context.get("timeline") or "",
                "search": context.get("search") or "",
                "dream": context.get("dream") or "",
            }
            return await _ok(
                {
                    "user": user,
                    "should_send": ok,
                    "reason": reason,
                    "sources": sources,
                    "text": text,
                }
            )
        except Exception as exc:
            logger.warning("[Storyteller] 主动试发预览失败: %s", exc)
            return await _fail(f"预览失败：{str(exc) or type(exc).__name__}")

    async def proactive_prompt_preview(self) -> Any:
        """预览「发送给主动模型 LLM 的完整提示词」：只读拼装，不调用 LLM。"""
        try:
            manager = self._plugin.proactive
            users = manager.target_users()
            user = users[0] if users else ""
            context = await manager._collect_context(user) if user else {}
            prompt = manager._build_prompt(context)
            from .models import resolve_chat_provider

            provider, provider_id = resolve_chat_provider(self._plugin.context, self._plugin.config, "proactive")
            return await _ok({
                "prompt": prompt,
                "model": provider_id or "（未配置，留空回退/驳回）",
                "length": len(prompt),
                "template_set": bool(str(self._plugin.config.get("proactive.template", "") or "").strip()),
            })
        except Exception as exc:
            logger.warning("[Storyteller] 主动提示词预览失败: %s", exc)
            return await _fail(f"预览失败：{str(exc) or type(exc).__name__}")

    async def proactive_trigger(self) -> Any:
        manager = self._plugin.proactive
        users = manager.target_users()
        if not users:
            return await _fail("未配置目标用户")
        import asyncio as _asyncio

        for user in users:
            _asyncio.ensure_future(manager._maybe_send(user, force=True))
        return await _ok({"triggered": True, "users": users})

    # ------------------------------------------------------------- Token

    async def token_stats(self) -> Any:
        """Token 统计（0.148 起四块）：companion 直连 / main 本插件代记主链 / astr_total 主链全部 / memory 记忆插件。"""
        try:
            stats = self._plugin.token_store.stats(source="companion")
            main = self._plugin.token_store.stats(source="main")
            astr = self._plugin.token_store.stats(source="astr_total")
        except Exception as exc:
            return await _fail(f"Token 统计失败: {exc}")
        memory = None
        try:
            bridge = self._plugin._get_memory_bridge()
            if bridge is not None:
                getter = getattr(bridge, "token_stats", None)
                if callable(getter):
                    memory = getter() or None
        except Exception:
            memory = None
        return await _ok({"stats": stats, "main": main, "astr_total": astr, "memory": memory})

    # ------------------------------------------------------------- 模型

    async def model_providers(self) -> Any:
        """模型列表（下拉数据源）：?kind=chat|embedding|rerank，与 AstrBot 的分类一致。

        chat=LLM 对话模型（get_all_providers）；embedding=嵌入模型（get_all_embedding_providers）；
        rerank=重排模型（AstrBot 无专用 context 接口，从 provider_manager 读）。
        多重回退：专用接口 → provider_manager.{kind}_provider_insts → inst_map 按 provider_type 过滤。
        """
        kind = str(_query("kind", "") or "").strip() or "chat"
        ctx = getattr(self._plugin, "context", None)
        insts: list[Any] = []
        seen: set[str] = set()

        def collect(inst: Any) -> None:
            try:
                meta = inst.meta()
                pid = str(getattr(meta, "id", "") or "")
            except Exception:
                pid = ""
            if not pid:
                cfg = getattr(inst, "provider_config", None) or {}
                pid = str(cfg.get("id", "") or "")
            if not pid or pid in seen:
                return
            seen.add(pid)
            label = pid
            try:
                model = str(inst.get_model() or "")
            except Exception:
                model = ""
            if model:
                label = f"{pid}（{model}）"
            insts.append({"id": pid, "label": label})

        try:
            if kind == "chat":
                getter = getattr(ctx, "get_all_providers", None)
                if callable(getter):
                    for p in getter() or []:
                        collect(p)
            else:
                fallback_attr = "rerank_provider_insts" if kind == "rerank" else "embedding_provider_insts"
                # 1) AstrBot 专用 context 接口（rerank 无）
                getter = getattr(ctx, f"get_all_{kind}_providers", None)
                if callable(getter):
                    for p in getter() or []:
                        collect(p)
                # 2) provider_manager 列表
                manager = getattr(ctx, "provider_manager", None)
                if manager is not None:
                    arr = getattr(manager, fallback_attr, None)
                    for p in arr or []:
                        collect(p)
                # 3) inst_map 按 provider_type 兜底（所有类型实例统一登记处）
                inst_map = getattr(manager, "inst_map", None) or {}
                for _pid, inst in inst_map.items():
                    cfg = getattr(inst, "provider_config", None) or {}
                    ptype = str(cfg.get("provider_type") or cfg.get("type") or "")
                    if ptype == kind or (kind == "embedding" and "embedding" in ptype) or \
                       (kind == "rerank" and "rerank" in ptype):
                        collect(inst)
        except Exception:
            pass
        return await _ok({"providers": insts, "kind": kind})

    # ------------------------------------------------------------- 表情包

    async def emoji_categories(self) -> Any:
        # 0.180：附带每分类的预览图（前 8 张 data URL）与文件数，供前端缩略图与逐张删除
        store = self._plugin.emoji_store
        categories = store.categories()
        for c in categories:
            cid = str(c.get("id") or "")
            if not cid:
                continue
            files = store.files_with_preview(cid, limit=8)
            c["files"] = files
            c["preview_total"] = len(store._files(cid)) if hasattr(store, "_files") else 0
        return await _ok({"categories": categories})

    async def emoji_category_add(self) -> Any:
        body = await _json_body(default={})
        title = str((body or {}).get("title") or "").strip()
        description = str((body or {}).get("description") or "").strip()
        try:
            result = self._plugin.emoji_store.add_category(title, description)
        except ValueError as exc:
            return await _fail(str(exc))
        return await _ok({"category": result, "categories": self._plugin.emoji_store.categories()})

    async def emoji_category_update(self) -> Any:
        body = await _json_body(default={})
        cid = str((body or {}).get("id") or "").strip()
        title = str((body or {}).get("title") or "").strip()
        description = str((body or {}).get("description") or "").strip()
        try:
            result = self._plugin.emoji_store.update_category(cid, title, description)
        except ValueError as exc:
            return await _fail(str(exc))
        return await _ok({"category": result, "categories": self._plugin.emoji_store.categories()})

    async def emoji_category_remove(self) -> Any:
        body = await _json_body(default={})
        cid = str((body or {}).get("id") or "").strip()
        self._plugin.emoji_store.remove_category(cid)
        return await _ok({"categories": self._plugin.emoji_store.categories()})

    async def emoji_upload(self) -> Any:
        """表情包上传：文件 multipart（files:upload 无 query 通道，分类 id 从文件名前缀传）。

        主流路径：文件名 = "<cid>__<原文件名>"（前端编码）；兼容旧版 ?cid 内联 query。
        """
        files = await _request_files()
        upload = files.get("file") if files else None
        if upload is None:
            return await _fail("缺少文件字段 file")
        filename = str(getattr(upload, "filename", "") or "")
        cid = ""
        if "__" in filename:
            cid = str(filename).split("__", 1)[0].strip()
        if not cid:
            cid = str(_query("cid", "") or "").strip()
        if not cid:
            return await _fail("缺少分类 id")
        try:
            content = await self._read_upload(upload)
            result = self._plugin.emoji_store.add_emoji(cid, filename, content)
        except ValueError as exc:
            return await _fail(str(exc))
        except Exception as exc:
            return await _fail(f"上传失败: {exc}")
        return await _ok(result)

    async def emoji_remove(self) -> Any:
        body = await _json_body(default={})
        cid = str((body or {}).get("id") or "").strip()
        filename = str((body or {}).get("file") or "").strip()
        self._plugin.emoji_store.remove_emoji(cid, filename)
        return await _ok({"categories": self._plugin.emoji_store.categories()})

    async def emoji_prefs(self) -> Any:
        """表情包策略：发送日志 / 分类权重 / opt-out 状态（面板展示）。"""
        store = self._plugin.emoji_store
        return await _ok({
            "prefs": store.preference_view() if hasattr(store, "preference_view") else {},
            "categories": store.categories(),
        })

    async def emoji_optout(self) -> Any:
        """手动切换某用户的表情包 opt-out 状态（参数：user / enabled）；也支持全清。"""
        body = await _json_body(default={})
        user = str((body or {}).get("user") or "").strip()
        enabled = bool((body or {}).get("enabled", True))
        store = self._plugin.emoji_store
        if user:
            store.set_opt_out(user, enabled)
        return await _ok({"opt_out": store.preference_view().get("opt_out", {}) if hasattr(store, "preference_view") else {}})

    async def send_status(self) -> Any:
        """发送缓冲页：队列状态 + 记录 + 配置。"""
        manager = getattr(self._plugin, "reply_buffer", None)
        if manager is None:
            return await _ok({"enabled": False, "queues": {}, "records": [], "interrupted": {}})
        return await _ok(manager.status())

    async def send_purge(self) -> Any:
        """清空发送缓冲（全部或指定会话）。"""
        body = await _json_body(default={})
        session_id = str((body or {}).get("session_id") or "").strip()
        manager = getattr(self._plugin, "reply_buffer", None)
        if manager is not None:
            manager.purge(session_id)
        return await _ok({"ok": True})

    # ------------------------------------------------------------- 内心世界

    async def mind_read(self) -> Any:
        return await _ok(self._plugin.mind_store.all())

    async def memory_read(self) -> Any:
        """记忆页：关联【为你篆刻的历史】插件的记忆库（最近记忆/约定/时间线，只读）。"""
        out: dict = {
            "available": False,
            "memories": [],
            "timeline": [],
            "note": "",
            "reason": "",
            "detail": "",
        }
        bridge = self._plugin._get_memory_bridge()
        status_getter = getattr(self._plugin, "_memory_bridge_status", None)
        status = status_getter() if callable(status_getter) else {}
        out["reason"] = str(status.get("reason") or "")
        out["detail"] = str(status.get("detail") or "")
        if bridge is None:
            out["note"] = (
                "未检测到【为你篆刻的历史】插件——{记忆} 占位符需要它提供长期记忆。"
                + (f"（{out['reason']}）" if out["reason"] else "")
            )
            return await _ok(out)
        out["available"] = True
        try:
            lister = getattr(bridge, "list_recent_memories", None)
            if callable(lister):
                records = lister(session_context={}, limit=30) or []
                for r in records[:30]:
                    text = ""
                    if isinstance(r, dict):
                        text = str(r.get("content") or r.get("summary") or r.get("text") or "")
                    elif hasattr(r, "content"):
                        text = str(r.content or "")
                    elif hasattr(r, "text"):
                        text = str(r.text or "")
                    if text:
                        out["memories"].append({
                            "text": text[:160],
                            "at": str(getattr(r, "created_at", "") or (r.get("created_at") if isinstance(r, dict) else ""))[:16],
                            "type": str(r.get("memory_type") if isinstance(r, dict) else (getattr(r, "memory_type", "") or "")),
                        })
        except Exception:
            pass
        try:
            tl = getattr(bridge, "get_timeline", None)
            if callable(tl):
                events = tl(session_context={}, limit=60) or []
                for e in events[:60]:
                    if isinstance(e, dict):
                        text = str(e.get("content") or "")[:100]
                        role = str(e.get("role") or "user")
                        scope = str(e.get("scope") or "")
                        user = str(e.get("user_name") or e.get("user_id") or "")
                        group = str(e.get("group_name") or e.get("group_id") or "")
                        at = str(e.get("occurred_at") or "")[:16]
                    else:
                        text = str(getattr(e, "content", "") or "")[:100]
                        role = str(getattr(e, "role", "") or "user")
                        scope = str(getattr(e, "scope", "") or "")
                        user = str(getattr(e, "user_name", "") or getattr(e, "user_id", "") or "")
                        group = str(getattr(e, "group_name", "") or getattr(e, "group_id", "") or "")
                        at = str(getattr(e, "occurred_at", "") or "")[:16]
                    if text:
                        out["timeline"].append({
                            "text": text,
                            "role": role,
                            "scope": scope,
                            "user": user,
                            "group": group,
                            "at": at,
                            "system": bool(e.get("is_system") if isinstance(e, dict) else getattr(e, "is_system", False)),
                            "kind": str(e.get("kind") if isinstance(e, dict) else (getattr(e, "kind", "") or "")) or "",
                        })
        except Exception:
            pass
        return await _ok(out)

    async def mind_generate(self) -> Any:
        """手动触发：做梦/冒个念头（创作类，保留模型思考）。"""
        body = await _json_body(default={})
        kind = str((body or {}).get("kind") or "")
        try:
            from .main import _hhmm
            from .mind import dream, think
            from .presence import build_presence_anchor
            from .schedule import current_activity

            import time as _time

            if kind == "dream":
                now = _time.strftime("%Y-%m-%d %H:%M", _time.localtime())
                presence = build_presence_anchor(self._plugin.presence_store.load())
                activities = []
                activity = current_activity(self._plugin.schedule_store.load(), _hhmm())
                if activity:
                    activities.append(f"此刻：{activity}")
                if presence:
                    activities.append(str(presence)[:200])
                text = await dream(self._plugin, day_context="；".join(activities), long_dream=False)
                if text:
                    self._plugin.mind_store.add_dream(text)
            elif kind == "think":
                text = await think(self._plugin)
                if text:
                    self._plugin.mind_store.add_thought(text)
            elif kind == "diary":
                await self._plugin._write_diary()
            else:
                return await _fail("未知生成类型")
            return await _ok({"entries": self._plugin.mind_store.all()})
        except Exception as exc:
            logger.warning("[Storyteller] 手动生成内心失败: %s", exc)
            return await _fail(f"生成失败：{str(exc) or type(exc).__name__}")

    async def mind_search(self) -> Any:
        """手动搜索见闻：输入关键词 → 搜索 → 整理成见闻并保存。"""
        body = await _json_body(default={})
        query = str((body or {}).get("query") or "").strip()
        if not query:
            return await _fail("请输入想搜的内容")
        try:
            from .mind import search_and_think

            result = await search_and_think(self._plugin, query)
            note = str(result.get("note") or "").strip()
            if note:
                self._plugin.mind_store.add_sighting(note)
                return await _ok({"note": note, "query": query, "entries": self._plugin.mind_store.all()})
            return await _fail("搜索无结果（检查「设置 → 搜索」的引擎与 API Key）")
        except Exception as exc:
            logger.warning("[Storyteller] 手动搜索见闻失败: %s", exc)
            return await _fail(f"搜索失败：{str(exc) or type(exc).__name__}")

    async def mind_delete(self) -> Any:
        """删除一条内心记录。"""
        body = await _json_body(default={})
        kind = str((body or {}).get("kind") or "")
        index = (body or {}).get("index")
        try:
            ok = self._plugin.mind_store.delete(kind, int(index))
        except Exception:
            ok = False
        if not ok:
            return await _fail("删除失败：记录不存在")
        return await _ok({"entries": self._plugin.mind_store.all()})

    # ------------------------------------------------------------- 日记

    async def diary_read(self) -> Any:
        return await _ok({"entries": self._plugin.diary_store.entries()})

    async def diary_prompt_preview(self) -> Any:
        """预览「写日记」实际发送给日记模型的完整提示词（只读拼装，不调用 LLM）。"""
        try:
            from .diary import build_diary_prompt
            from .models import resolve_chat_provider

            day_context = self._plugin._diary_material()
            prompt = build_diary_prompt(day_context)
            provider, provider_id = resolve_chat_provider(self._plugin.context, self._plugin.config, "diary")
            return await _ok(
                {
                    "prompt": prompt,
                    "model": provider_id or "（未配置，将留空回退/驳回）",
                    "length": len(prompt),
                    "material": day_context,
                }
            )
        except Exception as exc:
            logger.warning("[Storyteller] 日记提示词预览失败: %s", exc)
            return await _fail(f"预览失败：{str(exc) or type(exc).__name__}")

    # ------------------------------------------------------------- 衣柜与穿搭

    async def wardrobe_read(self) -> Any:
        return await _ok(self._plugin.wardrobe_store.load())

    async def wardrobe_outfit_update(self) -> Any:
        body = await _json_body(default={})
        items = body.get("items") if isinstance(body, dict) else None
        note = str((body or {}).get("note") or "").strip()
        wardrobe = self._plugin.wardrobe_store.set_outfit(items or [], note)
        return await _ok(wardrobe)

    async def wardrobe_closet_add(self) -> Any:
        body = await _json_body(default={})
        name = str((body or {}).get("name") or "").strip()
        category = str((body or {}).get("category") or "").strip()
        note = str((body or {}).get("note") or "").strip()
        try:
            wardrobe = self._plugin.wardrobe_store.add_item(name, category, note)
        except ValueError as exc:
            return await _fail(str(exc))
        return await _ok(wardrobe)

    async def wardrobe_closet_remove(self) -> Any:
        body = await _json_body(default={})
        name = str((body or {}).get("name") or "").strip()
        wardrobe = self._plugin.wardrobe_store.remove_item(name)
        return await _ok(wardrobe)

    async def wardrobe_generate(self) -> Any:
        """一键生成穿搭：直连 wardrobe.provider_id，从衣柜里选 2~5 件。"""
        try:
            from .models import resolve_chat_provider as _res_wgen
            from .wardrobe import build_wardrobe_generate_prompt, parse_wardrobe

            provider, provider_id = _res_wgen(self._plugin.context, self._plugin.config, "wardrobe_gen")
            if provider is None:
                return await _fail("穿搭生成模型未配置（请在穿搭页选择生成模型，或配置「留空回退模型」）")
            voice = self._plugin.voice_store.load()
            persona_desc = str(voice.get("tone") or "")
            weather = str(self._plugin.config.get("presence.weather", "") or "").strip()
            presence = str(getattr(self._plugin, "_presence_desc_stub", None) or "")
            closet = self._plugin.wardrobe_store.closet_items()
            prompt = build_wardrobe_generate_prompt(
                persona_desc=persona_desc, weather=weather, presence=presence, closet=closet, mode="outfit"
            )
            logger.info("[Storyteller] 开始生成穿搭（模型: %s）", provider_id or "default")
            resp = await chat_text(
                provider, self._plugin.config, prompt=prompt, session_id="storyteller_wardrobe_generate",
                _max_tokens=2000,  # 穿搭 JSON 很短，预算保险丝
            )
            self._plugin._record_usage(resp, "wardrobe_gen", provider_id or "default")
            raw_text = str(getattr(resp, "completion_text", "") or "")
            data = parse_wardrobe(raw_text)
            if not isinstance(data, dict) or not (data.get("items") or []):
                logger.warning(
                    "[Storyteller] 穿搭生成解析失败（原文 %s 字），前 120 字: %s",
                    len(raw_text), raw_text[:120].replace("\n", " "),
                )
                return await _fail("生成结果无法解析为穿搭，请重试")
            saved = self._plugin.wardrobe_store.set_outfit(
                [str(x).strip() for x in data.get("items") or [] if str(x).strip()],
                str(data.get("note") or "").strip()[:200],
            )
            return await _ok({"wardrobe": saved, "raw": str(getattr(resp, "completion_text", "") or "")[:2000]})
        except Exception as exc:
            logger.warning("[Storyteller] 一键生成穿搭失败: %s", exc)
            return await _fail(f"一键生成失败：{str(exc) or type(exc).__name__}")

    async def _generate_closet_items(self, count: int) -> tuple[list[dict[str, Any]], str]:
        """直连 wardrobe.provider_id 生成衣柜清单（不落库）；返回 (items, 错误)。

        0.151：注入人格注入体（性别/身份）+ 语气 + 天气 + 现有衣柜避重；
        生成结果做相似度去重（与现有衣柜明显不同款才返回）。
        """
        try:
            from .models import resolve_chat_provider as _res_wgen
            from .wardrobe import build_wardrobe_generate_prompt, parse_wardrobe

            provider, provider_id = _res_wgen(self._plugin.context, self._plugin.config, "wardrobe_gen")
            if provider is None:
                return [], "穿搭生成模型未配置（请在穿搭页选择生成模型，或配置「留空回退模型」）"
            voice = self._plugin.voice_store.load()
            persona_desc = str(voice.get("tone") or "")
            try:
                persona_injection = str(self._plugin.persona_store.injection_text() or "")
            except Exception:
                persona_injection = ""
            trigger = self._plugin.config
            identity_text = ""
            try:
                identity_text = str(trigger.get("identity.custom_text", "") or "").strip()[:400]
            except Exception:
                identity_text = ""
            if identity_text and identity_text not in persona_injection:
                persona_injection = (persona_injection + "\n" + identity_text).strip()
            closet = self._plugin.wardrobe_store.closet_items()
            existing_names = [str(c.get("name") or "") for c in closet if isinstance(c, dict)]
            prompt = build_wardrobe_generate_prompt(
                persona_desc=persona_desc, persona_injection=persona_injection,
                closet=closet, mode="closet", closet_count=count,
            )
            logger.info("[Storyteller] 开始生成衣柜清单（%s 件, 模型: %s）", count, provider_id or "default")
            resp = await chat_text(
                provider, self._plugin.config, prompt=prompt, session_id=f"storyteller_wardrobe_gen_{count}",
                _max_tokens=6000,
            )
            self._plugin._record_usage(resp, "wardrobe_gen", provider_id or "default")
            raw_text = str(getattr(resp, "completion_text", "") or "")
            data = parse_wardrobe(raw_text)
            if not isinstance(data, dict) or not (data.get("closet") or []):
                logger.warning(
                    "[Storyteller] 衣柜生成解析失败（原文 %s 字），前 120 字: %s",
                    len(raw_text), raw_text[:120].replace("\n", " "),
                )
                return [], "生成结果无法解析为衣柜，请重试"
            items = [it for it in (data.get("closet") or []) if isinstance(it, dict) and str(it.get("name") or "").strip()]
            # 0.151 去重：与现有衣柜及生成列表内部做相似度过滤（明显同款剔除）
            deduped = _dedupe_closet_items(items, existing_names)
            if not deduped:
                return [], "生成结果与现有衣柜几乎完全重复，请重试（已注入人格与避重提示）"
            return deduped[:count], ""
        except Exception as exc:
            logger.warning("[Storyteller] 衣柜生成失败: %s", exc)
            return [], f"生成失败：{str(exc) or type(exc).__name__}"

    async def wardrobe_generate_batch(self) -> Any:
        """一次生成十件（0.151）：预览不落库，返回待应用清单（每次生成右栏重置）。"""
        body = await _json_body(default={})
        count = max(1, min(20, int((body or {}).get("count") or 10)))
        items, err = await self._generate_closet_items(count)
        if err:
            return await _fail(err)
        return await _ok({"items": items})

    async def wardrobe_apply_batch(self) -> Any:
        """应用生成预览到衣柜（0.151）：容量校验，满则整体拒绝（提示衣柜已满）。"""
        body = await _json_body(default={})
        items = (body or {}).get("items") if isinstance(body, dict) else None
        if not isinstance(items, list) or not items:
            return await _fail("没有可应用的衣物")
        try:
            saved = self._plugin.wardrobe_store.add_items(items, important=False)
        except ValueError as exc:
            return await _fail(str(exc))
        except Exception as exc:
            return await _fail(f"应用失败：{str(exc) or type(exc).__name__}")
        return await _ok({"wardrobe": saved})

    async def wardrobe_replace_all(self) -> Any:
        """一键置换衣柜（0.151）：清空非重要衣物 + 生成 20 件直接置换（重要衣物保留）。"""
        items, err = await self._generate_closet_items(20)
        if err:
            return await _fail(err)
        saved = self._plugin.wardrobe_store.replace_all(items)
        return await _ok({"wardrobe": saved, "gen": len(items)})

    async def wardrobe_pin(self) -> Any:
        """手动「重要」标记切换（0.151）。"""
        body = await _json_body(default={})
        item_id = str((body or {}).get("item_id") or "")
        manual = bool((body or {}).get("manual"))
        if not item_id:
            return await _fail("缺少 item_id")
        saved = self._plugin.wardrobe_store.mark_item(item_id, manual)
        return await _ok({"wardrobe": saved})

    # ------------------------------------------------------------- 关系

    async def relationships_read(self) -> Any:
        return await _ok({"relationships": self._plugin.relationship_store.list_all()})

    async def relationships_update(self) -> Any:
        """手动调整人物卡（好感/称呼）；好感度自动重算阶段。"""
        body = await _json_body(default={})
        user_id = str((body or {}).get("user_id") or "")
        if not user_id:
            return await _fail("缺少 user_id")
        kwargs: dict = {}
        aff = (body or {}).get("affection")
        if aff is not None:
            kwargs["affection"] = aff
        if "address" in (body or {}):
            kwargs["address"] = str(body["address"])
        rel = self._plugin.relationship_store.update_manual(user_id, **kwargs)
        return await _ok({"relationship": rel})

    # ------------------------------------------------------------- UI 状态

    async def identity_editor(self) -> Any:
        """身份锚注入内容编辑器：自定义文本 + 最近一次自动生成的预览。"""
        custom = str(self._plugin.config.get("identity.custom_text", "") or "").strip()
        preview = str(getattr(self._plugin, "_last_identity_anchor", "") or "")
        return await _ok(
            {
                "custom": custom,
                "preview": preview,
                "empty_preview_hint": "尚无自动生成记录：发一条对话后，自动身份锚会缓存在此供预览。",
            }
        )

    async def ui_tab_order_read(self) -> Any:
        store = self._plugin.ui_state
        return await _ok({"order": store.load_order(), "default": KNOWN_TABS})

    async def ui_tab_order_update(self) -> Any:
        body = await _json_body(default={})
        order = (body or {}).get("order")
        if not self._plugin.ui_state.save_order(order):
            return await _fail("选项卡顺序不合法：必须包含全部选项卡且无重复")
        return await _ok({"order": self._plugin.ui_state.load_order()})
