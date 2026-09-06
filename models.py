"""模型配置：按功能细分的模型分流（模块内模型 + 全局留空回退策略）。

设计要点（独立实现，不与外部插件雷同）：
- 每个功能一个模型配置键，放在该功能所属的配置大类（模块）内，面板以下拉菜单形式选择；
- 「留空回退模型」策略（models 大类）：开启后，模块内模型留空时回退到全局回退模型；
  回退模型也为空 / 无效时，驳回该请求并输出报错日志；关闭后，模块内模型留空直接驳回报错；
- 模块内模型无效（配置了但找不到）同样驳回；
- 兼容旧版本：旧键 models.xxx_provider_id 仍有值时自动读取（迁移期不丢用户配置，保存写新键）；
- 嵌入模型特殊：嵌入提供商无法从聊天模型中挑选，留空回退到第一个可用嵌入 provider；
- 所有解析统一走本模块，保证「留空回退 / 驳回」口径一致。
"""

from __future__ import annotations

from typing import Any

from .log import logger

# 功能名 -> 配置键（各功能所属大类的模型键）
FUNCTION_KEYS = {
    "rewrite": "rewrite.provider_id",                # 二次润色
    "judge": "pipeline.provider_id",                 # 沉默/表情包/草草回复判定
    "emoji_judge": "emoji.judge_provider_id",        # 表情包语境判定（独立名额，可与判定模型不同）
    "vision": "vision.provider_id",                  # 多模态/识图
    "embedding": "memory.embedding_provider_id",     # 嵌入
    "presence": "presence.provider_id",              # 状态生成
    "schedule": "schedule.provider_id",              # 日程生成
    "proactive": "proactive.provider_id",            # 主动消息生成
    "dream": "mind.dream_provider_id",               # 梦境生成
    "search": "search.provider_id",                  # 搜索整理
    "profile": "memory.profile_provider_id",         # 用户画像提炼
    "commitment": "memory.commitment_provider_id",   # 约定/愿望提炼
    "think": "mind.think_provider_id",               # 无聊时思考
    "diary": "mind.diary_provider_id",               # 写日记
    "smart_judge": "debounce.smart_provider_id",     # 防抖智能判断（直连判定）
    "takeover": "intercept.provider_id",             # 拦截接管改换（直连生成回复）
    "interrupt": "send.interrupt_judge_provider_id", # 发送缓冲·抢话裁决（A/B）
    "voice_gen": "voice.provider_id",                # 一键生成风格档案（直连）
    "persona_gen": "persona.provider_id",            # 一键生成人格注入体（直连）
    "wardrobe_gen": "wardrobe.provider_id",          # 一键生成穿搭/衣柜（直连）
    "image_judge": "image.judge_provider_id",        # 生图意图仲裁（实验：规则未命中时轻量判定）
}

# 旧版本 models 大类的键（迁移期兼容读取）
_LEGACY_KEYS = {
    "rewrite": "models.rewrite_provider_id",
    "judge": "models.judge_provider_id",
    "vision": "models.vision_provider_id",
    "embedding": "models.embedding_provider_id",
    "presence": "models.presence_provider_id",
    "schedule": "models.schedule_provider_id",
    "proactive": "models.proactive_provider_id",
    "dream": "models.dream_provider_id",
    "search": "models.search_provider_id",
    "profile": "models.profile_provider_id",
    "commitment": "models.commitment_provider_id",
    "think": "models.think_provider_id",
    "diary": "models.diary_provider_id",
}

# 功能中文名（报错日志用）
_FUNCTION_CN = {
    "rewrite": "润色",
    "judge": "判定",
    "emoji_judge": "表情包判定",
    "vision": "识图",
    "embedding": "嵌入",
    "presence": "状态",
    "schedule": "日程",
    "proactive": "主动",
    "dream": "梦境",
    "search": "搜索",
    "profile": "画像",
    "commitment": "约定",
    "think": "思考",
    "diary": "日记",
    "smart_judge": "防抖判定",
    "takeover": "接管改换",
    "interrupt": "抢话裁决",
    "voice_gen": "风格生成",
    "persona_gen": "人格生成",
    "wardrobe_gen": "穿搭生成",
    "image_judge": "生图判断",
}


def function_cn(function: str) -> str:
    return _FUNCTION_CN.get(function, function)


def configured_id(config: Any, function: str) -> str:
    """读取某功能的模型配置（新键优先，旧 models.xxx 键兼容；空串表示未配置）。"""
    key = FUNCTION_KEYS.get(function)
    if not key or config is None:
        return ""
    value = str(config.get(key, "") or "").strip()
    if value:
        return value
    legacy = _LEGACY_KEYS.get(function)
    if legacy:
        old = str(config.get(legacy, "") or "").strip()
        if old:
            return old
    return ""


def fallback_enabled(config: Any) -> bool:
    """「留空回退模型」开关（models 大类，默认开启）。"""
    if config is None:
        return True
    return bool(config.bool("models.fallback_enabled", True))


def _lookup(context: Any, provider_id: str) -> Any:
    getter = getattr(context, "get_provider_by_id", None)
    if callable(getter):
        try:
            return getter(provider_id)
        except Exception:
            return None
    return None


def resolve_chat_provider(context: Any, config: Any, function: str) -> tuple[Any, str]:
    """解析对话类模型（模块内模型 → 留空回退模型 → 驳回）。

    成功返回 (provider, provider_id)；失败返回 (None, "") 并输出报错日志（调用方应判空跳过）。
    """
    provider_id = configured_id(config, function)
    cn = function_cn(function)
    if provider_id:
        provider = _lookup(context, provider_id)
        if provider is not None:
            return provider, provider_id
        logger.error("[%s] 模型配置无效: %s（已驳回该请求）", cn, provider_id)
        return None, ""
    # 模块内留空：走「留空回退模型」策略
    if fallback_enabled(config):
        fallback_id = str(config.get("models.fallback_provider_id", "") or "").strip()
        if fallback_id:
            provider = _lookup(context, fallback_id)
            if provider is not None:
                return provider, fallback_id
            logger.error("[模型] 回退模型无效: %s（已驳回【%s】请求）", fallback_id, cn)
            return None, ""
        logger.error("[模型] 回退模型为空：【%s】模型未配置且回退模型为空（已驳回该请求）", cn)
        return None, ""
    logger.error("[模型] 【%s】模型未配置，且「留空回退模型」已关闭（已驳回该请求）", cn)
    return None, ""


def resolve_embedding_provider(context: Any, config: Any) -> tuple[Any, str]:
    """解析嵌入模型（严格模式：不做任何自动回退）。

    嵌入模型来自独立的 embedding 提供商配置（与对话 LLM 完全分开），
    不参与「留空回退模型」策略（回退模型从对话 LLM 中选择，类型不匹配）。
    模块内未配置或配置无效 → 返回 (None, "") 并输出报错日志，调用方应跳过/报错。
    """
    provider_id = configured_id(config, "embedding")
    if provider_id:
        provider = _lookup(context, provider_id)
        if provider is not None:
            return provider, provider_id
        logger.error("[嵌入] 嵌入模型无效: %s（已驳回嵌入请求）", provider_id)
        return None, ""
    logger.error(
        "[嵌入] 嵌入模型未配置（嵌入不走「留空回退模型」，请到记忆页选择嵌入分类下的模型；已驳回嵌入请求）"
    )
    return None, ""


async def text_chat(provider: Any, *, prompt: str, session_id: str, **kwargs: Any) -> str:
    """直连 provider 做一次文本生成，返回 completion_text（失败返回空串）。"""
    if provider is None or not prompt:
        return ""
    try:
        method = getattr(provider, "text_chat", None)
        if not callable(method):
            return ""
        resp = await method(prompt=prompt, session_id=session_id, persist=False, **kwargs)
        return str(getattr(resp, "completion_text", "") or "").strip()
    except Exception:
        return ""


class _ChatResult:
    """统一直连结果：兼容 resp.completion_text / resp.usage 的访问方式。

    流式聚合时 usage 取最后一个带 usage 的 chunk（AstrBot 流式末尾 chunk 含 usage）；
    非流式时直接包住原 resp。
    est_input_tokens：输入文本的估算 token（提供方没返回 usage 时供记账兜底）。
    """

    def __init__(self, completion_text: str = "", usage: Any = None, est_input_tokens: int = 0):
        self.completion_text = completion_text
        self.usage = usage
        self.est_input_tokens = max(0, int(est_input_tokens or 0))


class _StreamEarlyAbort(RuntimeError):
    """流式生成的确定性放弃（思考风暴 / 内容超长跑飞）。

    与超时、断网等偶发失败不同：同一提示词重试几乎必然同样失败，
    因此不重试，直接回退非流式（通用策略，与具体模型/提供方无关）。
    """


class _ThinkingParamRejected(RuntimeError):
    """提供方不认「关闭思考」参数（HTTP 400/422）：去掉该参数重试一次。

    这是通用容错：不同提供方对未知参数的处理不一，有的静默忽略、
    有的直接报错；报错时去掉参数再试就能兼容任何一家。
    """


class _DirectUnavailable(RuntimeError):
    """直连不可用（环境缺 httpx / 提取不到直连信息），交由原通道处理。"""


def _extract_openai_direct(provider: Any) -> dict | None:
    """从 AstrBot provider 对象提取 OpenAI 兼容「直连上游」所需信息。

    仅做防御性读取，无任何提供方特判：base_url/api_key/model 任一缺失、
    或属于 Azure 等需要额外认证参数的形式，一律返回 None（回退原通道）。
    """
    try:
        if provider is None:
            return None
        client = getattr(provider, "client", None)
        if client is None:
            return None
        # Azure OpenAI 走 api_version 等附加认证，直连格式不适用
        if getattr(client, "api_version", None):
            return None
        base_url = str(getattr(client, "base_url", "") or "").strip().rstrip("/")
        api_key = str(getattr(client, "api_key", "") or "").strip()
        get_model = getattr(provider, "get_model", None)
        model = str(get_model() if callable(get_model) else "") or ""
        if not base_url or not api_key or not model:
            return None
        if not base_url.startswith(("http://", "https://")):
            return None
        return {"base_url": base_url, "api_key": api_key, "model": model}
    except Exception:
        return None


def _direct_messages(system_prompt: str, prompt: str) -> list[dict]:
    """组装直连 messages：0.167 修复——此前 system_prompt 被直连通道丢弃（实机"没看到设定"根因）。"""
    msgs: list[dict] = []
    sys = str(system_prompt or "").strip()
    if sys:
        msgs.append({"role": "system", "content": sys})
    msgs.append({"role": "user", "content": str(prompt or "")})
    return msgs


def _usage_from_dict(u: Any) -> Any:
    """把直连上游返回的 usage 字典转成插件内部统一的 usage 对象。

    插件消费方（token 记账 / 测试）统一读 input_other/input_cached/output，
    与 AstrBot LLMResponse.usage 的字段协议一致。
    """
    if u is None:
        return None
    try:
        prompt = int(u.get("prompt_tokens") or 0)
        completion = int(u.get("completion_tokens") or 0)
        from types import SimpleNamespace

        return SimpleNamespace(input_other=prompt, input_cached=0, output=completion)
    except Exception:
        return None


async def _direct_stream(
    info: dict,
    prompt: str,
    *,
    disable_thinking: bool,
    max_think_chars: int,
    max_chars: int,
    max_tokens: int | None = None,
    system_prompt: str = "",
) -> _ChatResult:
    """直连上游流式生成（OpenAI 兼容 /chat/completions）。

    - 绕开 AstrBot 客户端写死的超时墙（SDK 超时在客户端创建时定死，
      本通道按块读取、超时完全自控）；
    - disable_thinking=True 时附带通用「关闭思考」参数
      {"thinking": {"type": "disabled"}}（DeepSeek 官方标准格式，
      各主流 OpenAI 兼容服务通用）；
    - max_tokens 为生成预算上限（保险丝）：正常输出在预算内自然收尾；
      只有模型跑飞才被截断（finish_reason=length），超限生成不完整时
      由调用方的解析/重试兜底；
    - 聚合沿用同一套「快照去重 + 思考风暴/超长早停」逻辑。
    """
    try:
        import httpx
    except ImportError:
        raise _DirectUnavailable("环境无 httpx，无法直连") from None
    import json as _json

    body: dict = {
        "model": info["model"],
        "messages": _direct_messages(system_prompt, prompt),
        "stream": True,
    }
    if disable_thinking:
        body["thinking"] = {"type": "disabled"}
    if max_tokens is not None and max_tokens > 0:
        body["max_tokens"] = int(max_tokens)
    url = f"{info['base_url']}/chat/completions"
    headers = {"Authorization": f"Bearer {info['api_key']}", "Content-Type": "application/json"}

    parts: list[str] = []
    usage = None
    think_chars = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=15, read=90, write=30, pool=10)) as client:
        async with client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code in (400, 422) and disable_thinking:
                raise _ThinkingParamRejected("提供方不认「关闭思考」参数")
            if resp.status_code != 200:
                buf = await resp.aread()
                raise RuntimeError(
                    f"直连上游 HTTP {resp.status_code}: {buf.decode('utf-8', 'replace')[:150]}"
                )
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    evt = _json.loads(payload)
                except Exception:
                    continue
                if evt.get("usage"):
                    usage = evt["usage"]
                choices = evt.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                if choice.get("finish_reason"):
                    break
                delta = choice.get("delta") or {}
                think = str(delta.get("reasoning_content") or "")
                if think:
                    think_chars += len(think)
                    if think_chars > max_think_chars:
                        raise _StreamEarlyAbort(
                            f"模型思考过长（>{max_think_chars} 字符），已放弃本次尝试"
                        )
                text = str(delta.get("content") or "")
                if text:
                    joined = "".join(parts)
                    js, ts = joined.strip(), text.strip()
                    if js and ts:
                        if ts == js:
                            # 完全重复块（上游重发同文本）：忽略，保留已聚合
                            pass
                        elif len(ts) > len(js) and ts.startswith(js):
                            # 更长的整段快照：替换为新全量
                            parts = [text]
                        else:
                            # 其余一律追加——包括「恰好是已聚合文本前缀」的短增量
                            # （0.176 修复：真实流式模型按 1~8 字符增量输出，每个对象开头的
                            #   {" 是独立分片且必为已拼文本前缀；旧逻辑把它当重复快照丢弃，
                            #   导致 JSON 每个对象开头的 {" 全部丢失、解析必失败）
                            parts.append(text)
                    else:
                        parts.append(text)
                    if len("".join(parts)) > max_chars:
                        raise _StreamEarlyAbort(
                            f"生成内容超长（>{max_chars} 字符），已截断放弃"
                        )
    if not parts and usage is None:
        raise RuntimeError("直连流式返回空内容")
    return _ChatResult("".join(parts), _usage_from_dict(usage))


async def _direct_nonstream(
    info: dict, prompt: str, *, disable_thinking: bool, max_tokens: int | None = None, system_prompt: str = ""
) -> _ChatResult:
    """直连上游一次性生成（非流式），同样绕开客户端超时墙并可关闭思考。"""
    try:
        import httpx
    except ImportError:
        raise _DirectUnavailable("环境无 httpx，无法直连") from None
    import json as _json

    body: dict = {
        "model": info["model"],
        "messages": _direct_messages(system_prompt, prompt),
        "stream": False,
    }
    if disable_thinking:
        body["thinking"] = {"type": "disabled"}
    if max_tokens is not None and max_tokens > 0:
        body["max_tokens"] = int(max_tokens)
    url = f"{info['base_url']}/chat/completions"
    headers = {"Authorization": f"Bearer {info['api_key']}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=15, read=90, write=30, pool=10)) as client:
        async with client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code in (400, 422) and disable_thinking:
                raise _ThinkingParamRejected("提供方不认「关闭思考」参数")
            if resp.status_code != 200:
                buf = await resp.aread()
                raise RuntimeError(
                    f"直连上游 HTTP {resp.status_code}: {buf.decode('utf-8', 'replace')[:150]}"
                )
            buf = await resp.aread()
    try:
        data = _json.loads(buf.decode("utf-8", "replace"))
    except Exception as exc:
        raise RuntimeError(f"直连非流式响应解析失败: {exc}") from exc
    content = ""
    choices = data.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = str(message.get("content") or "")
    return _ChatResult(content, _usage_from_dict(data.get("usage")))


async def chat_text(provider: Any, config: Any, *, prompt: str, session_id: str, **kwargs: Any) -> Any:
    """统一直连生成入口（直连优先 + 流式 + 单次限时 + 自动重试，纯插件侧解决）。

    - **直连上游优先**（models.direct_enabled 默认开，仅对 OpenAI 兼容提供方生效）：
      从 provider 对象提取 base_url/api_key/model，自建 httpx 请求——
      ① 绕开 AstrBot 客户端写死的超时墙（SDK 超时创建客户端时定死，
         非流式 30s/120s 必死，本通道超时完全自控）；
      ② 可附带通用「关闭思考」参数（models.disable_thinking 默认开）：
         推理模型默认对简单任务长时间思考（数分钟），关闭后结构化生成
         10~20 秒完成（实测两主流 DeepSeek V4 渠道均从 45s+ 降到 10~20s）；
      ③ 提供方不认该参数（400/422）时自动去掉参数重试一次；
      ④ 直连任何失败自动回退下方原通道（AstrBot provider 流式/非流式）。
      创作类调用点可传 _disable_thinking=False 保留思考（接管回复/润色等）。
    - models.stream_enabled 默认开启：原通道优先 text_chat_stream（逐 chunk 聚合）。
      部分上游的 OpenAI 兼容接口在非流式长生成时会超过客户端超时（默认 120s）
      而报「Request timed out」；流式逐 chunk 返回更稳（与具体提供方无关的通用策略）；
    - **单次尝试限时**（models.stream_timeout 默认 120s）：每次流式尝试用 asyncio.wait_for
      包住，超时立即放弃该次（不会无限挂在"生成中"）；失败自动重试
      （models.stream_retry 默认 1，共 2 次尝试）；再失败回退非流式；
    - **全量快照去重**：AstrBot 流式末尾会再发一个"整段文本"chunk，与增量互为前缀时
      只保留更长者（否则正文翻倍、JSON 解析必失败——生成成功却不落盘的根因）；
    - **思考风暴/超长早停**：reasoning_content 累计超 models.stream_max_think_chars
      （默认 8000）或正文超 models.stream_max_chars（默认 12000）时立即放弃本次尝试；
    - 非流式同样限时（同一 stream_timeout），超时抛异常交给调用方；
    - 接入方无需改 AstrBot 配置：无论 AstrBot provider 的 timeout 是多少，
      本封装都先用"直连 + 流式 + 限时 + 重试"兜底；
    - 开关关闭：直接非流式（限时仍生效，与旧行为一致）。
    返回对象始终有 completion_text / usage（可能为 None），供 _record_usage 与解析复用。
    """
    import asyncio

    if provider is None or not prompt:
        return _ChatResult()
    stream_enabled = True
    retry_count = 1
    timeout_sec = 120.0
    max_chars = 12000
    max_think_chars = 24000
    direct_enabled = True
    disable_thinking = True
    default_max_tokens = 4000
    try:
        if config is not None:
            stream_enabled = bool(config.bool("models.stream_enabled", True))
            retry_count = max(0, int(config.int("models.stream_retry", 1) or 1))
            timeout_sec = float(max(10, int(config.int("models.stream_timeout", 120) or 120)))
            max_chars = max(2000, int(config.int("models.stream_max_chars", 12000) or 12000))
            max_think_chars = max(1000, int(config.int("models.stream_max_think_chars", 24000) or 24000))
            direct_enabled = bool(config.bool("models.direct_enabled", True))
            disable_thinking = bool(config.bool("models.disable_thinking", True))
            default_max_tokens = max(256, int(config.int("models.stream_max_tokens", 4000) or 4000))
    except Exception:
        stream_enabled = True
        retry_count = 1
        timeout_sec = 120.0
        max_chars = 12000
        max_think_chars = 24000
        direct_enabled = True
        disable_thinking = True
        default_max_tokens = 4000
    # 调用点覆盖：创作类任务（接管回复/润色/做梦等）可显式传 _disable_thinking=False，保留模型思考；
    # 结构化任务可传 _max_tokens 作生成预算保险丝（防跑飞超长输出）
    override = kwargs.pop("_disable_thinking", None)
    if override is not None:
        disable_thinking = bool(override)
    max_tokens = kwargs.pop("_max_tokens", None)
    if max_tokens is not None:
        try:
            max_tokens = int(max_tokens)
        except (TypeError, ValueError):
            max_tokens = default_max_tokens
    else:
        max_tokens = default_max_tokens
    # 0.167：system_prompt 从 kwargs 取出（直连与原通道都要显式携带；此前直连丢弃导致模型"没看到设定"）
    direct_system = str(kwargs.pop("system_prompt", "") or "")

    # 成功结果统一挂「输入估算」：提供方没返回 usage 时，记账侧用它对输入兜底
    from .token_usage import estimate_tokens

    def _finalize(result: Any) -> Any:
        if isinstance(result, _ChatResult) and not result.est_input_tokens:
            result.est_input_tokens = estimate_tokens(prompt)
        return result

    # ── 直连上游优先（OpenAI 兼容）：可附带「关闭思考」参数、绕开客户端超时墙 ──
    if direct_enabled:
        direct_info = _extract_openai_direct(provider)
        if direct_info is not None:
            from .log import logger

            async def _direct_call(think: bool) -> _ChatResult:
                if stream_enabled:
                    return await _direct_stream(
                        direct_info, prompt,
                        disable_thinking=think,
                        max_think_chars=max_think_chars,
                        max_chars=max_chars,
                        max_tokens=max_tokens,
                        system_prompt=direct_system,
                    )
                return await _direct_nonstream(
                    direct_info, prompt, disable_thinking=think, max_tokens=max_tokens,
                    system_prompt=direct_system,
                )

            try:
                r = await asyncio.wait_for(_direct_call(disable_thinking), timeout=timeout_sec)
                logger.info(
                    "[Storyteller] 直连生成成功（模型: %s%s）",
                    direct_info["model"], "" if disable_thinking else "，保留思考",
                )
                return _finalize(r)
            except _ThinkingParamRejected:
                logger.warning("[Storyteller] 直连上游不认「关闭思考」参数，去掉该参数重试一次")
                try:
                    r = await asyncio.wait_for(_direct_call(False), timeout=timeout_sec)
                    logger.info("[Storyteller] 直连生成成功（模型: %s，保留思考）", direct_info["model"])
                    return _finalize(r)
                except Exception as exc2:
                    logger.warning("[Storyteller] 直连生成失败（%s），回退原通道", str(exc2)[:150])
            except Exception as exc:
                logger.warning("[Storyteller] 直连生成失败（%s），回退原通道", str(exc)[:150])

    async def _collect_stream() -> _ChatResult:
        parts: list[str] = []
        usage = None
        think_chars = 0
        async for chunk in stream_method(
            prompt=prompt, session_id=session_id, persist=False, system_prompt=direct_system, **kwargs
        ):            # 思考内容（reasoning_content）：不进正文，但累计长度——
            # 推理模型陷入长时间思考风暴时提前放弃本次尝试（不等超时）
            think = str(getattr(chunk, "reasoning_content", "") or "")
            if think:
                think_chars += len(think)
                if think_chars > max_think_chars:
                    raise _StreamEarlyAbort(
                        f"模型思考过长（>{max_think_chars} 字符），已放弃本次尝试"
                    )
            text = str(getattr(chunk, "completion_text", "") or "")
            if text:
                joined = "".join(parts)
                # 快照去重（0.176 修复判定边界）：AstrBot 流式在末尾会再 yield 一个
                # 「全量快照」chunk（completion_text = 整段完整文本），只有「完全相等
                # 的重复块」与「以已聚合文本为前缀的更长全量」才需要去重/替换；
                # 其余一律追加——真实流式的增量分片（模型逐 1~8 字符输出，每个对象
                # 开头的 {" 是独立分片且必为已拼文本前缀）绝不能再当重复快照丢弃，
                # 否则 JSON 每个对象开头的 {" 全部丢失、解析必失败。
                js, ts = joined.strip(), text.strip()
                if js and ts:
                    if ts == js:
                        # 完全重复块（上游重发同文本）：忽略，保留已聚合
                        pass
                    elif len(ts) > len(js) and ts.startswith(js):
                        # 更长的整段快照：替换为新全量
                        parts = [text]
                    else:
                        # 其余一律追加（增量分片，含恰好为已拼文本前缀的短块）
                        parts.append(text)
                else:
                    parts.append(text)
                if len("".join(parts)) > max_chars:
                    raise _StreamEarlyAbort(f"生成内容超长（>{max_chars} 字符），已截断放弃")
            u = getattr(chunk, "usage", None)
            if u is not None:
                usage = u
        if not parts and usage is None:
            raise RuntimeError("流式返回空内容")
        return _ChatResult("".join(parts), usage)

    if stream_enabled:
        stream_method = getattr(provider, "text_chat_stream", None)
        if callable(stream_method):
            last_exc: Exception | None = None
            for attempt in range(max(1, retry_count + 1)):  # 初始 1 次 + retry_count 次重试
                try:
                    return _finalize(await asyncio.wait_for(_collect_stream(), timeout=timeout_sec))
                except _StreamEarlyAbort as exc:
                    from .log import logger

                    # 确定性失败（思考风暴/内容跑飞）：重试同一提示词几乎必然同样失败，
                    # 跳过重试直接回退非流式，省下整段空等（通用策略，与提供方无关）。
                    last_exc = exc
                    logger.warning(
                        "[Storyteller] 流式生成确定性放弃（%s），跳过重试直接回退非流式",
                        str(exc)[:120],
                    )
                    break
                except Exception as exc:
                    from .log import logger

                    last_exc = exc
                    logger.warning(
                        "[Storyteller] 流式生成尝试 %s/%s 失败（%s），%s",
                        attempt + 1, max(1, retry_count + 1), type(exc).__name__, str(exc)[:120],
                    )
                    if attempt < retry_count:
                        await asyncio.sleep(1.0)
            if last_exc is not None:
                from .log import logger

                logger.info("[Storyteller] 流式全部失败，回退非流式（上次错误: %s）", str(last_exc)[:120])
    method = getattr(provider, "text_chat", None)
    if not callable(method):
        return _ChatResult()

    async def _collect_nonstream() -> _ChatResult:
        try:
            resp = await method(prompt=prompt, session_id=session_id, persist=False, system_prompt=direct_system, **kwargs)
        except TypeError:
            # 个别 provider/桩不接受 system_prompt 参数：去掉再试（无系统提示直接拼 prompt 头由调用方兜底）
            resp = await method(prompt=prompt, session_id=session_id, persist=False, **kwargs)
        return _ChatResult(str(getattr(resp, "completion_text", "") or ""), getattr(resp, "usage", None))

    try:
        return _finalize(await asyncio.wait_for(_collect_nonstream(), timeout=timeout_sec))
    except TimeoutError as exc:
        hint = (
            f"生成超时（单次限时 {int(timeout_sec)}s）：模型响应过慢，可能在长时间思考；"
            "可在「设置 → 模型配置」调大单次限时，或为该功能换用非推理模型"
        )
        detail = str(exc).strip()
        raise RuntimeError(f"{hint}（上游详情: {detail}）" if detail else hint) from exc