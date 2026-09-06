"""内心活动：做梦 / 搜索网页 / 思考。

设计要点（独立实现，不与外部插件雷同）：
- 搜索支持 bing / tavily 两种引擎（下拉选择 + apikey + 结果数）；
- 做梦与思考由对应模型生成，结果供状态与主动对话使用；
- 全部为后台/直连调用，不走主链，失败静默降级。
"""

from __future__ import annotations

import json
from typing import Any

from .log import logger
from .models import chat_text, resolve_chat_provider


async def _http_get_json(url: str, *, headers: dict[str, str], timeout: int = 15) -> Any:
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=timeout) as resp:
                return await resp.json()
    except Exception:
        return None


async def _http_post_json(url: str, *, headers: dict[str, str], payload: dict, timeout: int = 15) -> Any:
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=timeout) as resp:
                return await resp.json()
    except Exception:
        return None


async def search_web(plugin: Any, query: str) -> list[dict[str, str]]:
    """搜索网页，返回 [{title, url, snippet}]。"""
    if not query or not query.strip():
        return []
    config = plugin.config
    engine = str(config.get("search.engine", "tavily") or "tavily").strip().lower()
    api_key = str(config.get("search.api_key", "") or "").strip()
    count = max(1, min(10, config.int("search.result_count", 3)))
    if not api_key:
        return []
    if engine == "bing":
        return await _bing_search(api_key, query, count)
    if engine == "tavily":
        return await _tavily_search(api_key, query, count)
    return []


async def _bing_search(api_key: str, query: str, count: int) -> list[dict[str, str]]:
    data = await _http_get_json(
        "https://api.bing.microsoft.com/v7.0/search",
        headers={"Ocp-Apim-Subscription-Key": api_key},
    )
    return _parse_search_results(data, count)


async def _tavily_search(api_key: str, query: str, count: int) -> list[dict[str, str]]:
    data = await _http_post_json(
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        payload={"query": query, "max_results": count},
    )
    results = data.get("results") if isinstance(data, dict) else None
    out: list[dict[str, str]] = []
    if isinstance(results, list):
        for r in results[:count]:
            if isinstance(r, dict):
                out.append(
                    {
                        "title": str(r.get("title") or "")[:120],
                        "url": str(r.get("url") or "")[:300],
                        "snippet": str(r.get("content") or r.get("snippet") or "")[:400],
                    }
                )
    return out


def _parse_search_results(data: Any, count: int) -> list[dict[str, str]]:
    pages = data.get("webPages", {}).get("value", []) if isinstance(data, dict) else None
    out: list[dict[str, str]] = []
    if isinstance(pages, list):
        for p in pages[:count]:
            if isinstance(p, dict):
                out.append(
                    {
                        "title": str(p.get("name") or "")[:120],
                        "url": str(p.get("url") or "")[:300],
                        "snippet": str(p.get("snippet") or "")[:400],
                    }
                )
    return out


async def generate_text(plugin: Any, function: str, prompt: str, *, task: str) -> str:
    """直连对应功能模型生成一段文本（做梦/思考等），返回文本。"""
    try:
        provider, provider_id = resolve_chat_provider(plugin.context, plugin.config, function)
        if provider is None:
            return ""
        resp = await chat_text(
            provider, plugin.config, prompt=prompt, session_id=f"storyteller_{task}",
            _disable_thinking=False,  # 做梦/思考属创作：保留模型思考
        )
        store = getattr(plugin, "token_store", None)
        if store is not None:
            try:
                usage = getattr(resp, "usage", None)
                if usage is not None:
                    inp = int(getattr(usage, "input_other", 0) or 0) + int(getattr(usage, "input_cached", 0) or 0)
                    out = int(getattr(usage, "output", 0) or 0)
                    store.record(task=task, model=provider_id or "default", input_tokens=inp, output_tokens=out)
            except Exception:
                pass
        return str(getattr(resp, "completion_text", "") or "").strip()
    except Exception as exc:
        logger.warning("[Storyteller] %s 生成失败: %s", task, exc)
        return ""


async def dream(plugin: Any, *, day_context: str = "", long_dream: bool = True) -> str:
    """生成一段梦境。

    long_dream=True（深夜一整夜的连贯长梦）：提示词强调一段连贯、有情节的长梦，
    揉合白天素材；普通手动（白天）则一句简短片段。
    """
    if long_dream:
        prompt = (
            "为这个角色生成一段一整夜的连贯长梦。"
            "要自然、克制、像人真正做的梦：有片段、有情绪、有点跳，但前后是一回事，"
            "可以代入白天看到的、听到的、心里惦记的事，把它揉进梦里，"
            "但不要编造夸张剧情，不要总结成故事。输出梦境本身，一段话（80~200 字），简体中文。"
            + (f"\n\n她最近的经历与心头事（可自然揉进梦里的素材）：\n{day_context}" if day_context else "")
        )
    else:
        prompt = (
            "为这个角色生成一段简短的梦境。要自然、克制、像人做的梦，"
            "可以由最近的状态、思绪、见闻或回忆揉合而成，不要编造夸张剧情。"
            "只输出梦境内容本身，一两句话，简体中文。"
            + (f"\n今天的状态/见闻：{day_context}" if day_context else "")
        )
    return await generate_text(plugin, "dream", prompt, task="dream")


async def think(plugin: Any, *, topic: str = "") -> str:
    """生成一段「闲时思考」。topic 为这阵子发生的由头。"""
    prompt = (
        "这个角色现在有点空闲，脑子里在转一个念头。请生成一句自然的内心独白或思考，"
        "要克制、像真人偶尔发呆时冒出的想法，不要总结、不要长篇。"
        "只输出这句话本身，简体中文。"
        + (f"\n\n她刚刚经历/注意到的事（念头要顺着它来）：{topic}" if topic else "")
    )
    return await generate_text(plugin, "think", prompt, task="think")


async def search_and_think(plugin: Any, query: str) -> dict[str, Any]:
    """搜索网页并用搜索结果整理成一段可分享的见闻。"""
    results = await search_web(plugin, query)
    if not results:
        return {"query": query, "results": [], "note": ""}
    lines = "\n".join(f"- {r['title']}: {r['snippet']}" for r in results)
    prompt = (
        "下面是刚搜索到的一些网页结果。请把它们整理成一句自然的、可以主动分享给别人的见闻，"
        "要克制、像真人刷到东西随口说一句，不要罗列链接、不要总结成报告。只输出这句话，简体中文。\n\n"
        + lines
    )
    note = await generate_text(plugin, "search", prompt, task="search")
    return {"query": query, "results": results, "note": note}


async def browse(plugin: Any, *, force: bool = False) -> dict[str, Any]:
    """「无聊时上网刷新鲜事」：按间隔节流；force=True 忽略间隔（手动触发）。

    生成成功（有见闻文本）才更新 last_browse_at，避免"搜了没结果/没 key"
    时把间隔消耗掉。返回 {ok, note, skipped, reason}。
    """
    import time as _time

    store = getattr(plugin, "mind_store", None)
    interval = max(2, (plugin.config.int("search.browse_interval_hours", 6) or 6)) * 3600
    if not force:
        last = float(store.meta_get("last_browse_at", 0) or 0)
        if _time.time() - last < interval:
            return {"ok": False, "note": "", "skipped": True, "reason": "间隔未到"}
    if not plugin.config.bool("search.browse_enabled", True) and not force:
        return {"ok": False, "note": "", "skipped": True, "reason": "自主搜索已关闭"}
    result = await search_and_think(plugin, "最近有什么新鲜事")
    note = str(result.get("note") or "").strip()
    if note:
        store.add_sighting(note)
        store.meta_set("last_browse_at", _time.time())
    return {"ok": bool(note), "note": note, "skipped": False, "reason": "" if note else "搜索无结果或无 key"}


class MindStore:
    """内心世界（梦境/思考/见闻）的存储与读取。"""

    def __init__(self, data_dir: Any):
        import json as _json
        from pathlib import Path as _Path

        self._json = _json
        self._file = _Path(data_dir) / "mind.json"
        self._data: dict[str, Any] = {"dreams": [], "thoughts": [], "sightings": [], "_meta": {}}
        self._load()

    def _load(self) -> None:
        try:
            if self._file.exists():
                raw = self._json.loads(self._file.read_text(encoding="utf-8-sig"))
                if isinstance(raw, dict):
                    for key in ("dreams", "thoughts", "sightings"):
                        if isinstance(raw.get(key), list):
                            self._data[key] = raw[key]
                    if isinstance(raw.get("_meta"), dict):
                        self._data["_meta"] = raw["_meta"]
        except Exception:
            pass

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(
                self._json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _push(self, key: str, text: str, limit: int = 20) -> None:
        text = (text or "").strip()
        if not text:
            return
        import time as _time

        entry = {"text": text[:500], "at": _time.strftime("%Y-%m-%d %H:%M", _time.localtime())}
        self._data[key].insert(0, entry)
        if len(self._data[key]) > limit:
            self._data[key] = self._data[key][:limit]
        self._save()

    def add_dream(self, text: str) -> None:
        self._push("dreams", text)

    def add_thought(self, text: str) -> None:
        self._push("thoughts", text)

    def add_sighting(self, text: str) -> None:
        self._push("sightings", text)

    def delete(self, kind: str, index: int) -> bool:
        """删除某类第 index 条（0 为最新）。越界或类型非法返回 False。"""
        try:
            if kind not in ("dreams", "thoughts", "sightings"):
                return False
            i = int(index)
            items = self._data.get(kind, [])
            if i < 0 or i >= len(items):
                return False
            del items[i]
            self._save()
            return True
        except Exception:
            return False

    def all(self) -> dict[str, Any]:
        return {
            "dreams": self._data.get("dreams", []),
            "thoughts": self._data.get("thoughts", []),
            "sightings": self._data.get("sightings", []),
        }

    def meta_get(self, key: str, default: Any = None) -> Any:
        return self._data.get("_meta", {}).get(key, default)

    def meta_set(self, key: str, value: Any) -> None:
        self._data.setdefault("_meta", {})[key] = value
        self._save()
