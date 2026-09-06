"""媒体感知：组合消息（表情包/图片/文件文档/链接/语音视频）的「像人」理解与注入。

设计取向（独立实现，不与外部插件雷同）：
- 回复侧（接管/放行共用）：识图转述、文件摘要、链接标题与要点并行组织成「对方还附带发了…」，
  并带**克制引导**——提不提图片由模型判断，表情包类降级为轻标记，不做复读机式点评；
- 动图：PIL 均匀抽 N 帧，同一次识图同时传入多帧做连贯理解（默认 3 帧，可配）；
- 文档：文本类 + Word/PPT/Excel（zip 标准库提取）+ PDF（pypdf，有则用）；超过上限自动分块全读汇总；
- 表情区分：Face（系统表情，id→名称映射）vs Image（图片）；图片内「表情包/梗图」由识图语义裁决，
  规则辅助信号（GIF/小尺寸/方形比例）在提示词里加权；
- 预算克制：全部外部调用可配超时与重试（vision.media_retry），失败静默降级为基础标记。
"""

from __future__ import annotations

import asyncio
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .log import logger
from .models import resolve_chat_provider

# 文本类 + Office 文档白名单
_DOCUMENT_EXTENSIONS = {
    ".txt", ".md", ".json", ".yaml", ".yml", ".log", ".csv",
    ".py", ".js", ".ts", ".html", ".xml", ".ini", ".cfg", ".conf", ".toml",
    ".docx", ".pptx", ".xlsx", ".xlsm", ".pdf",
}

# QQ 常用系统表情 id → 名称（常见子集；未命中显示「表情」）
FACE_NAMES = {
    0: "惊讶", 1: "撇嘴", 2: "色", 3: "发呆", 4: "得意", 5: "流泪", 6: "害羞",
    7: "闭嘴", 8: "睡", 9: "大哭", 10: "尴尬", 11: "发怒", 12: "调皮", 13: "呲牙",
    14: "微笑", 15: "难过", 16: "酷", 17: "抠鼻", 18: "哭", 19: "抓狂", 20: "吐",
    21: "咦", 22: "愉快", 23: "白眼", 24: "傲慢", 25: "困", 26: "惊恐", 27: "流汗",
    28: "憨笑", 29: "悠闲", 30: "奋斗", 31: "咒骂", 32: "疑问", 33: "嘘", 34: "晕",
    35: "折磨", 36: "衰", 37: "骷髅", 38: "敲打", 39: "再见", 42: "鼓掌", 43: "糗大了",
    44: "坏笑", 45: "左哼哼", 46: "右哼哼", 47: "哈欠", 48: "鄙视", 49: "委屈",
    50: "快哭了", 51: "阴险", 52: "亲亲", 53: "吓", 54: "可怜", 55: "菜刀", 56: "西瓜",
    57: "啤酒", 58: "篮球", 59: "乒乓", 60: "咖啡", 61: "饭", 62: "猪头", 63: "玫瑰",
    64: "凋谢", 65: "嘴唇", 66: "爱心", 67: "心碎", 68: "蛋糕", 69: "闪电", 70: "炸弹",
    71: "刀", 72: "足球", 73: "便便", 74: "月亮", 75: "太阳", 76: "礼物", 77: "拥抱",
    78: "强", 79: "弱", 80: "握手", 81: "胜利", 82: "抱拳", 83: "勾引", 84: "拳头",
    85: "差劲", 86: "爱你", 87: "NO", 88: "OK", 96: "发抖", 97: "啵啵", 98: "委屈",
    278: "狗头", 279: "抱抱", 281: "哭泣", 290: "吃瓜", 292: "笑哭", 293: "裂开",
    294: "盯", 295: "哦", 300: "棒", 305: "叹气", 311: "大笑", 314: "疑问",
}


def _comp_parts(event: Any) -> list[Any]:
    message_obj = getattr(event, "message_obj", None)
    if message_obj is None:
        return []
    chain = getattr(message_obj, "message", None)
    return chain if isinstance(chain, list) else []


def face_name(face_id: Any) -> str:
    try:
        return FACE_NAMES.get(int(face_id), "")
    except Exception:
        return ""


def extract_media_parts(event: Any) -> dict[str, Any]:
    """轻量分类提取事件里的媒体（不调 LLM）。

    返回：{"images": [url...], "faces": [(id,名称)...], "files": [{name,path,url}],
          "videos": [name...], "records": [name...], "urls": [url...],
          "has_media": bool, "text": 文本}
    """
    out: dict[str, Any] = {
        "images": [], "faces": [], "files": [], "videos": [], "records": [],
        "urls": [], "has_media": False, "text": "",
    }
    text_part = ""
    for comp in _comp_parts(event):
        cls = type(comp).__name__
        if cls in ("Image", "Face"):
            url = str(getattr(comp, "url", "") or getattr(comp, "file", "") or "")
            if url:
                out["images"].append(url[:500])
                out["has_media"] = True
            elif cls == "Face":
                name = face_name(getattr(comp, "id", ""))
                out["faces"].append((str(getattr(comp, "id", "") or ""), name))
                out["has_media"] = True
        elif cls == "File":
            out["files"].append({
                "name": str(getattr(comp, "name", "") or "")[:200],
                "path": str(getattr(comp, "file_", "") or "")[:500],
                "url": str(getattr(comp, "url", "") or "")[:500],
            })
            out["has_media"] = True
        elif cls == "Video":
            out["videos"].append(str(getattr(comp, "file", "") or getattr(comp, "name", "") or "视频")[:120])
            out["has_media"] = True
        elif cls == "Record":
            out["records"].append(str(getattr(comp, "file", "") or "语音")[:120])
            out["has_media"] = True
        elif cls == "Share":
            url = str(getattr(comp, "url", "") or "")
            if url:
                out["urls"].append(url[:500])
                out["has_media"] = True
        elif cls == "Plain":
            text_part += str(getattr(comp, "text", "") or "")
    out["text"] = text_part
    # 文本里的链接始终提取（组合消息里文字也可能带链接，去重）
    found = re.findall(r"https?://[^\s<>\"']+", text_part)
    for u in found[:5]:
        if u[:500] not in out["urls"]:
            out["urls"].append(u[:500])
    if out["urls"]:
        out["has_media"] = True
    return out


def extract_images(event: Any) -> list[str]:
    parts = extract_media_parts(event)
    return parts["images"]


# ------------------------------------------------------------ 通用重试

async def _call_with_retry(plugin: Any, coro_factory, label: str, timeout: float) -> Any:
    """带超时与重试（vision.media_retry）的调用封装；最终失败返回 None。"""
    retry = 0
    try:
        retry = max(0, int(plugin.config.int("vision.media_retry", 0)))
    except Exception:
        retry = 0
    last_exc: Exception | None = None
    for attempt in range(retry + 1):
        try:
            return await asyncio.wait_for(coro_factory(), timeout=timeout)
        except asyncio.TimeoutError:
            last_exc = TimeoutError(f"{label} 超时({timeout:.0f}s)")
        except Exception as exc:
            last_exc = exc
    logger.warning("[Storyteller] %s 在 %s 次尝试后失败: %s", label, retry + 1, last_exc)
    return None


# ------------------------------------------------------------ 识图（分层 + 动图多帧）

def _img_kind_prompt(signal: str = "") -> str:
    base = (
        "请先判断这张图的类型，再按类型转述。输出格式：类型标记 + 一句话转述，例如「[表情] 发了个无语的表情」或「[图片] 夕阳下的街道」。\n"
        "判断规则：\n"
        "- 表情包/梗图/动图截图（主要表达情绪、语气、状态或梗）→ 类型 [表情]，"
        "只简短说明「TA 发了表达（何种情绪/状态）的表情包」，不描述画面细节；\n"
        "- 真实照片、截图、作品、有信息量的图（风景、物品、文档截图、画作等）→ 类型 [图片]，简要描述关键内容。\n"
        "- 拿不准时归为 [表情] 更稳妥（多数人发图是分享情绪，而不是要你点评画面）。\n"
        "用第三人称、一句话以内、中文，不要加「图片里是」这类开头。"
    )
    if signal:
        base = f"{signal}\n{base}"
    return base


def _gif_frames_prompt() -> str:
    return (
        "这是同一张动态表情包/动图的 3 帧（按时间顺序）。请连贯理解它整体在表达什么情绪或梗，"
        "再按规则转述：类型标记 + 一句话。例如「[表情] 这个动图在表达无语到裂开」。"
        "用第三人称、一句话以内、中文。"
    )


async def _extract_gif_frames(plugin: Any, image_url: str, frame_count: int) -> list[str] | None:
    """本地抽 GIF 的 N 帧 → PNG 临时文件列表；失败返回 None。"""
    try:
        from PIL import Image as PILImage

        local = ""
        if image_url.startswith(("http://", "https://")):
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return None
                    raw = await resp.read()
            tmp = Path(tempfile.gettempdir()) / f"storyteller_gif_{abs(hash(image_url))}.gif"
            tmp.write_bytes(raw)
            local = str(tmp)
        else:
            local = image_url
            if not Path(local).exists():
                return None
        with PILImage.open(local) as img:
            if img.format != "GIF" and not getattr(img, "is_animated", False):
                return None
            total = getattr(img, "n_frames", 1)
            if total <= 1:
                frames = [0]
            else:
                idxs = {round(i * (total - 1) / max(1, frame_count - 1)) for i in range(frame_count)}
                frames = sorted(idxs)
            outs: list[str] = []
            for i in frames:
                img.seek(i)
                frame = img.convert("RGB")
                path = Path(tempfile.gettempdir()) / f"storyteller_gif_{abs(hash(image_url))}_f{i}.png"
                frame.save(path, "PNG")
                outs.append(str(path))
            return outs
    except Exception as exc:
        logger.warning("[Storyteller] 动图抽帧失败: %s", exc)
        return None


async def caption_images(plugin: Any, image_urls: list[str]) -> tuple[str, str]:
    """直连识图模型转述图片，返回 (kind, text)；kind ∈ sticker|photo|unknown。

    - 多图：同一调用传入；动图（gif）自动抽 N 帧连贯理解；
    - 失败重试 vision.media_retry 次；无模型/失败返回 ("", "")。
    """
    if not image_urls:
        return "", ""
    try:
        provider, provider_id = resolve_chat_provider(plugin.context, plugin.config, "vision")
        if provider is None:
            return "", ""
        method = getattr(provider, "text_chat", None)
        if not callable(method):
            return "", ""
        gif_frames = 3
        try:
            gif_frames = max(1, min(9, int(plugin.config.int("vision.gif_frames", 3) or 3)))
        except Exception:
            gif_frames = 3
        send_urls: list[str] = []
        prompt = _img_kind_prompt()
        animated = False
        for url in image_urls[:4]:
            if url.lower().endswith(".gif") or "gif" in url.lower():
                frames = await _extract_gif_frames(plugin, url, gif_frames)
                if frames:
                    send_urls.extend(frames)
                    animated = True
                    continue
            send_urls.append(url)
        if animated and len(send_urls) >= 2:
            prompt = _gif_frames_prompt()

        def _call():
            return method(
                prompt=prompt,
                image_urls=send_urls[:6],
                session_id="storyteller_vision",
                persist=False,
            )

        resp = await _call_with_retry(plugin, _call, "识图", 20)
        if resp is None:
            return "", ""
        store = getattr(plugin, "token_store", None)
        if store is not None:
            try:
                usage = getattr(resp, "usage", None)
                if usage is not None:
                    inp = int(getattr(usage, "input_other", 0) or 0) + int(getattr(usage, "input_cached", 0) or 0)
                    out = int(getattr(usage, "output", 0) or 0)
                    store.record(task="vision", model=provider_id or "default", input_tokens=inp, output_tokens=out)
            except Exception:
                pass
        text = str(getattr(resp, "completion_text", "") or "").strip()
        if not text:
            return "", ""
        kind = "unknown"
        if text.startswith("[表情]"):
            kind = "sticker"
            text = text[len("[表情]"):].strip()
        elif text.startswith("[图片]"):
            kind = "photo"
            text = text[len("[图片]"):].strip()
        return kind, text[:400]
    except Exception as exc:
        logger.warning("[Storyteller] 识图失败: %s", exc)
        return "", ""


def _guidance_for(kind: str) -> str:
    """分层转述 + 克制引导：表情包降级为轻标记；照片/截图给详细转述但提示不必刻意点评。"""
    if kind == "sticker":
        return "对方发了个表情包，别当成必须回应的内容；顺带提一句或不提都自然。"
    return "对方发来一张图，值得接话时可以自然提起；不必对每一张图都点评。"


async def caption_and_inject(plugin: Any, event: Any, req: Any) -> None:
    """把图片转述注入请求（分层：表情包轻标记 / 照片详细转述 + 克制引导）。"""
    images = extract_images(event)
    if not images:
        return
    kind, caption = await caption_images(plugin, images)
    if not caption:
        return
    parts = getattr(req, "extra_user_content_parts", None)
    if parts is None:
        parts = []
        req.extra_user_content_parts = parts
    try:
        from astrbot.api.message_components import Plain

        if kind == "sticker":
            parts.append(Plain(text=f"（对方发了个表情包：{caption}。{_guidance_for('sticker')}）"))
        else:
            parts.append(Plain(text=f"（对方发来的图片：{caption}。{_guidance_for(kind)}）"))
        logger.info("[Storyteller] 已注入图片转述: kind=%s %s", kind, caption[:60])
    except Exception:
        pass


# ------------------------------------------------------------ 文档：全套格式 + 分块全读

def _extract_document_text(path: str) -> str:
    """按扩展名提取文档纯文本（zip 标准库 / pypdf；失败返回空串）。"""
    try:
        p = Path(path)
        suffix = p.suffix.lower()
        raw_limit = 1 * 1024 * 1024  # 1MB 上限防炸
        if suffix in (".docx", ".pptx", ".xlsx", ".xlsm"):
            if not zipfile.is_zipfile(p):
                return ""
            with zipfile.ZipFile(p) as z:
                if suffix in (".docx",):
                    xml_names = ["word/document.xml"]
                    tag = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
                elif suffix == ".pptx":
                    xml_names = sorted(
                        n for n in z.namelist()
                        if re.match(r"ppt/slides/slide\d+\.xml$", n)
                    )
                    tag = "{http://schemas.openxmlformats.org/drawingml/2006/main}t"
                else:  # xlsx 取共享字符串，够了会意用
                    xml_names = ["xl/sharedStrings.xml"]
                    tag = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"
                parts_text: list[str] = []
                for name in xml_names[:200]:
                    if name not in z.namelist():
                        continue
                    xml = z.read(name)[:raw_limit].decode("utf-8", errors="replace")
                    text = "".join(re.findall(rf"<{re.escape(str(tag))}[^>]*>(.*?)</{re.escape(str(tag))}>", xml, re.S))
                    parts_text.append(re.sub(r"\s+", " ", text).strip())
                joined = " ".join(part for part in parts_text if part)
                return joined[:500000]
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
            except Exception:
                try:
                    from PyPDF2 import PdfReader
                except Exception:
                    return ""
            reader = PdfReader(str(p))
            pages: list[str] = []
            for page in reader.pages[:120]:
                try:
                    t = (page.extract_text() or "").strip()
                except Exception:
                    t = ""
                if t:
                    pages.append(t)
            text = "\n".join(pages)
            return text[:500000]
        return ""
    except Exception:
        return ""


async def _summarize_long(plugin: Any, text: str, name: str, retry: int) -> str:
    """长文档分块全读汇总（像人从头读到尾再归纳）。"""
    chunk = 12000
    blocks = [text[i:i + chunk] for i in range(0, len(text), chunk)][:8]
    provider, provider_id = resolve_chat_provider(plugin.context, plugin.config, "vision")
    if provider is None:
        return ""
    from .models import chat_text

    notes: list[str] = []
    for idx, block in enumerate(blocks):
        prompt = (
            f"这是文档「{name}」的第 {idx + 1}/{len(blocks)} 部分。请用 2-3 句话记下这一部分的关键点"
            "（供整体理解用，不要遗漏重要事实）：\n\n" + block
        )

        def _call():
            return chat_text(provider, plugin.config, prompt=prompt, session_id="storyteller_media_file", _max_tokens=220)

        resp = await _call_with_retry(plugin, _call, "长文档分块", 20)
        if resp is not None:
            notes.append(str(getattr(resp, "completion_text", "") or "").strip()[:400])
            plugin._record_usage(resp, "media_file", provider_id or "default")
    if not notes:
        return ""
    joined = "\n".join(f"- {n}" for n in notes if n)

    def _merge():
        return chat_text(
            provider, plugin.config,
            prompt=f"以下是长文档「{name}」各部分的要点。请综合成 3-4 句连贯的整体概括（供回复时自然接话）：\n\n{joined}",
            session_id="storyteller_media_file", _max_tokens=320,
        )

    resp = await _call_with_retry(plugin, _merge, "长文档汇总", 20)
    if resp is None:
        return joined[:500]
    plugin._record_usage(resp, "media_file", provider_id or "default")
    return str(getattr(resp, "completion_text", "") or "").strip()[:500]


async def summarize_file(plugin: Any, item: dict) -> str:
    """文档读取（文本类 + docx/pptx/xlsx/pdf）：>上限自动分块全读汇总；失败返回空串。"""
    path = str(item.get("path") or "") or str(item.get("url") or "")
    if not path:
        return ""
    try:
        doc_path = Path(path)
        if doc_path.suffix.lower() not in _DOCUMENT_EXTENSIONS:
            return ""
        if not doc_path.exists():
            return ""
        max_chars = 40000
        try:
            max_chars = max(2000, min(200000, int(plugin.config.int("vision.file_max_chars", 40000) or 40000)))
        except Exception:
            max_chars = 40000
        if doc_path.suffix.lower() in (".docx", ".pptx", ".xlsx", ".xlsm", ".pdf"):
            text = _extract_document_text(str(doc_path))
        else:
            text = doc_path.read_text(encoding="utf-8", errors="replace")
        if len(text.strip()) < 20:
            return ""
        if len(text) > max_chars:
            return await _summarize_long(plugin, text[:200000], item.get("name") or "文档", retry=0)
    except Exception:
        return ""
    provider, provider_id = resolve_chat_provider(plugin.context, plugin.config, "vision")
    if provider is None:
        return ""
    from .models import chat_text

    snippet = text[:max_chars]

    def _call():
        return chat_text(
            provider, plugin.config,
            prompt="请用 2-3 句话概括以下文档内容（供回复时自然接话，不要编造）：\n\n" + snippet,
            session_id="storyteller_media_file", _max_tokens=220,
        )

    resp = await _call_with_retry(plugin, _call, "文档摘要", 20)
    if resp is None:
        return ""
    plugin._record_usage(resp, "media_file", provider_id or "default")
    return str(getattr(resp, "completion_text", "") or "").strip()[:400]


# ------------------------------------------------------------ 链接：标题 + 要点

async def fetch_link_context(url: str, *, timeout: float = 8.0) -> str:
    """拉取网页标题 + meta 描述 + 首段纯文本（最大 64KB，失败返回空串）。"""
    try:
        import aiohttp

        headers = {
            "User-Agent": "Mozilla/5.0 (AstrBot Storyteller Media Reader)",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    return ""
                raw = (await resp.content.read(65536)).decode("utf-8", errors="replace")
    except Exception:
        return ""
    title = ""
    desc = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
    for pattern in (
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']',
    ):
        m = re.search(pattern, raw, re.S | re.I)
        if m:
            desc = re.sub(r"\s+", " ", m.group(1)).strip()[:500]
            if desc:
                break
    body = re.sub(r"<script.*?</script>", " ", raw, flags=re.S | re.I)
    body = re.sub(r"<style.*?</style>", " ", body, flags=re.S | re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\s+", " ", body).strip()
    parts = [p for p in (title, desc, body[:600]) if p]
    return " | ".join(parts)[:1200]


async def summarize_link(plugin: Any, url: str, *, fetcher=None) -> str:
    """链接「标题+要点」：抓取网页上下文 → LLM 一句话要点（失败降级为标题/域名）。"""
    context = ""
    if fetcher is not None:
        try:
            context = await fetcher(url)
        except Exception:
            context = ""
    else:
        context = await fetch_link_context(url)
    if not context:
        try:
            from urllib.parse import urlparse

            host = urlparse(url).netloc or url
            return f"[链接] {host}"
        except Exception:
            return f"[链接] {url[:80]}"
    try:
        provider, provider_id = resolve_chat_provider(plugin.context, plugin.config, "vision")
        if provider is None:
            return f"[链接] {context[:200]}"
        from .models import chat_text

        def _call():
            return chat_text(
                provider, plugin.config,
                prompt=(
                    "这是用户刚发来的一个链接的网页信息（标题/描述/开头文字）。\n"
                    f"{context}\n\n"
                    "用一句话说出「这条链接大致是什么、对方发来大概想说什么」，用于像人一样自然接话；"
                    "拿不准时只给标题即可，不要编造。简体中文。"
                ),
                session_id="storyteller_media_link", _max_tokens=150,
            )

        resp = await _call_with_retry(plugin, _call, "链接要点", 15)
        if resp is None:
            return f"[链接] {context[:200]}"
        plugin._record_usage(resp, "media_link", provider_id or "default")
        text = str(getattr(resp, "completion_text", "") or "").strip()
        return f"[链接] {text[:300]}" if text else f"[链接] {context[:200]}"
    except Exception as exc:
        logger.warning("[Storyteller] 链接要点失败: %s", exc)
        return f"[链接] {context[:200]}"


# ------------------------------------------------------------ 统一会意（并行 + 分层）

async def build_media_note(
    plugin: Any,
    event: Any,
    *,
    with_llm: bool = True,
    max_chars: int = 800,
    include_images: bool = True,
    include_face: bool = True,
) -> str:
    """把整条组合消息组织成一句「还附带发了…」（接管直连前调用）。

    图片/文件/链接三类会意并行执行；表情包类降级为轻标记；with_llm=False 只出基础标记。
    """
    parts = extract_media_parts(event)
    if not parts["has_media"]:
        return ""

    async def _image_note() -> tuple[str, str]:
        if not (include_images and parts["images"]):
            return "", ""
        kind, caption = await caption_images(plugin, parts["images"])
        if caption:
            if kind == "sticker":
                return "sticker", f"[表情] {caption}"
            return "photo", f"[图片] {caption}"
        return "", f"[图片×{len(parts['images'])}]"

    async def _file_note() -> str:
        if not parts["files"]:
            return ""
        item = parts["files"][0]
        name = item.get("name") or "文件"
        if with_llm:
            summary = await summarize_file(plugin, item)
            return f"[文件] {name}" + (f"：{summary}" if summary else "")
        return f"[文件] {name}"

    async def _link_note(url: str) -> str:
        if with_llm:
            note = await summarize_link(plugin, url)
            return note
        return f"[链接] {url[:120]}"

    tasks: list[Any] = []
    if with_llm:
        tasks.append(_image_note())
        tasks.append(_file_note())
    for url in parts["urls"][:2]:
        tasks.append(_link_note(url))
    results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []

    lines: list[str] = []
    idx = 0
    if with_llm:
        img_result = results[idx] if results else None
        idx += 1
        if isinstance(img_result, tuple) and len(img_result) == 2 and img_result[1]:
            lines.append(img_result[1])
    elif parts["images"]:
        lines.append(f"[图片×{len(parts['images'])}]")
    # 表情 face id → 名称
    if include_face and parts["faces"]:
        for fid, name in parts["faces"][:3]:
            lines.append(f"[表情：{name or '表情'}]" if name else "[表情]")
    # 文件
    file_result = None
    if with_llm and results:
        r = results[idx] if idx < len(results) else None
        idx += 1
        if isinstance(r, str):
            file_result = r
    if file_result:
        lines.append(file_result)
    elif with_llm and parts["files"]:
        lines.append(f"[文件] {parts['files'][0].get('name') or '文件'}")
    elif not with_llm and parts["files"]:
        lines.append(f"[文件] {parts['files'][0].get('name') or '文件'}")
    # 链接
    if with_llm:
        for i in range(idx, len(results)):
            r = results[i]
            if isinstance(r, str) and r.startswith("[链接]"):
                lines.append(r)
    elif parts["urls"]:
        for url in parts["urls"][:2]:
            lines.append(f"[链接] {url[:120]}")
    # 视频 / 语音
    if parts["videos"]:
        lines.append(f"[视频] {parts['videos'][0]}")
    if parts["records"]:
        lines.append(f"[语音] {parts['records'][0]}")
    # 识图失败且 with_llm 时补基础图片标记
    if with_llm and parts["images"] and not any(l.startswith(("[图片]", "[表情]")) for l in lines):
        lines.append(f"[图片×{len(parts['images'])}]")
    text = "；".join(l for l in lines if l)
    return text[:max_chars]


async def build_ordered_media_script(plugin: Any, event: Any, *, with_llm: bool = True, max_chars: int = 800) -> str:
    """保序脚本（0.169）：按组件链原始顺序渲染「对方发的这一轮内容」为带行文本。

    媒体行内嵌会意（识图转述/文件摘要/链接标题）且保留在原始位置——多条连发时
    "帮我看看这个/[文档]/算了不用了" 的顺序与语义不再错位（build_media_note 聚合式丢失位置）。
    多条时加 ①②③ 编号；无组件链/无内容返回空（调用方回退原文本+聚合 note 逻辑）。
    """
    try:
        message_obj = getattr(event, "message_obj", None)
        chain = getattr(message_obj, "message", None)
        if not isinstance(chain, list) or not chain:
            return ""
        parts = extract_media_parts(event) if with_llm else None
        # 会意预取（与 build_media_note 同成本：单图单独转述，多图聚合一句）
        single_img_caption = ""
        multi_img_caption = ""
        img_urls = ((parts or {}).get("images") or [])
        if img_urls:
            if len(img_urls) == 1:
                _, cap = await caption_images(plugin, img_urls[:1])
                single_img_caption = cap or ""
            else:
                _, cap = await caption_images(plugin, img_urls[:4])
                multi_img_caption = cap or ""
        file_note = ""
        file_items = ((parts or {}).get("files") or [])
        if file_items and with_llm:
            file_note = await summarize_file(plugin, file_items[0]) or ""
        link_note = ""
        link_urls = ((parts or {}).get("urls") or [])
        if link_urls and with_llm:
            note = await summarize_link(plugin, link_urls[0])
            link_note = str(note or "")[:200]

        lines: list[str] = []
        text_buf: list[str] = []

        def flush_text() -> None:
            if text_buf:
                joined = "".join(text_buf).strip()
                if joined:
                    lines.append(joined)
                text_buf.clear()

        for comp in chain:
            cls = type(comp).__name__
            if cls == "Plain":
                part = str(getattr(comp, "text", "") or getattr(comp, "content", "") or "")
                if part:
                    text_buf.append(part)
            elif cls == "Image":
                flush_text()
                lines.append(f"[图片：{single_img_caption}]" if single_img_caption else "[图片]")
            elif cls == "Face":
                flush_text()
                name = str(getattr(comp, "name", "") or getattr(comp, "text", "") or "表情")
                lines.append(f"[表情：{name}]" if name != "表情" else "[表情]")
            elif cls == "File":
                flush_text()
                name = str(getattr(comp, "name", "") or "文件")
                line = f"[文档/文件：{name}]"
                if file_note:
                    line += f"：{file_note}"
                lines.append(line)
            elif cls == "Share":
                flush_text()
                lines.append("[分享]")
            elif cls == "Video":
                flush_text()
                lines.append("[视频]")
            elif cls == "Record":
                flush_text()
                lines.append("[语音]")
            else:
                txt = str(getattr(comp, "text", "") or getattr(comp, "content", "") or "")
                if txt.strip():
                    text_buf.append(txt)
        flush_text()
        if multi_img_caption:
            lines.append(f"（多张图片的内容：{multi_img_caption}）")
        if link_note:
            lines.append(f"（其中一个链接：{link_note}）")
        lines = [ln.strip() for ln in lines if ln.strip()]
        # 纯文本多条（组件链合并为单 Plain 但含换行）：拆行后同样编号
        if len(lines) == 1 and "\n" in lines[0]:
            lines = [ln.strip() for ln in lines[0].split("\n") if ln.strip()]
        if not lines:
            return ""
        if len(lines) > 1:
            marks = "①②③④⑤⑥⑦⑧⑨⑩"
            out = "\n".join(
                f"{marks[i] if i < len(marks) else str(i + 1)}{ln}" for i, ln in enumerate(lines)
            )
        else:
            out = lines[0]
        return out[:max_chars]
    except Exception:
        return ""


async def attach_file_link_notes(plugin: Any, event: Any, req: Any) -> None:
    """放行模式：把文件/链接会意（不含图片，图片走 caption_and_inject）注入请求。"""
    parts = extract_media_parts(event)
    if not (parts["files"] or parts["urls"]):
        return
    note = await build_media_note(
        plugin, event, with_llm=True, max_chars=800,
        include_images=False, include_face=False,
    )
    if not note:
        return
    out = getattr(req, "extra_user_content_parts", None)
    if out is None:
        out = []
        req.extra_user_content_parts = out
    try:
        from astrbot.api.message_components import Plain

        out.append(Plain(text=f"（对方还附带发了：{note}）"))
        logger.info("[Storyteller] 已注入文件/链接会意: %s", note[:80])
    except Exception:
        pass