"""统一的 LLM 判定层：能交给模型判断的，就不要写死规则。

## 规矩（R6，2026-10-27 起）

> **能调用 LLM 做智能判定的，就不要写规则。**

原因（真机教训）：规则永远覆盖不全，而且会**短路**本该由模型判断的分支。
典型事故：「你做一个文档」里的「做」被当成绘画触发词、「一个」被当成画图量词，
生图模块直接判定"要画一张图"并 return —— 连 LLM 都没被问到，工具更没机会。

## 规则在这里的角色

**只当兜底值，不当判据。** 流程是：

```
① 缓存命中 → 直接返回（省钱、省时）
② 调 LLM 判定（超时 6 秒、输出限定几个词）
③ 解析成功 → 用模型的判断
④ 任何失败（没 provider / 超时 / 胡说）→ 用规则的判断（只能"保底"，不能"抢先"）
```

## 代价控制

- 同一个问题 + 同一段文本 → 缓存 10 分钟（同样的消息只判一次）；
- 每个判定器有日限额（默认 300），超了直接用兜底值；
- 输出强制是**一个词**（从候选里选），便于解析、省 token。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

DEFAULT_TIMEOUT = 6.0
DEFAULT_DAILY_LIMIT = 300
CACHE_TTL = 600
MAX_TEXT = 500

PROMPT_TEMPLATE = """判断下面这句话属于哪一类，只输出一个词。

候选：{options}

这句话：
{text}

只输出候选里的一个词，不要解释、不要标点。"""


class JudgeError(Exception):
    """判定失败（内部用，调用方一律走兜底）。"""


@dataclass
class JudgeBudget:
    daily_limit: int = DEFAULT_DAILY_LIMIT
    counts: dict[str, int] = field(default_factory=dict)

    def _today(self) -> str:
        return time.strftime("%Y-%m-%d", time.localtime())

    def left(self) -> int:
        return max(0, self.daily_limit - int(self.counts.get(self._today(), 0)))

    def take(self) -> bool:
        day = self._today()
        if self.left() <= 0:
            return False
        self.counts[day] = int(self.counts.get(day, 0)) + 1
        return True


@dataclass
class JudgeResult:
    value: str
    source: str          # llm / cache / fallback
    raw: str = ""
    note: str = ""

    @property
    def used_llm(self) -> bool:
        return self.source in ("llm", "cache")


class Judge:
    """一个判定器。构造时给问题、候选值、兜底值，之后反复调用 judge()。"""

    def __init__(
        self,
        name: str,
        *,
        options: tuple[str, ...],
        fallback: str,
        instruction: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        daily_limit: int = DEFAULT_DAILY_LIMIT,
    ) -> None:
        if fallback not in options:
            raise ValueError(f"兜底值 {fallback!r} 必须在候选里")
        self.name = name
        self.options = tuple(options)
        self.fallback = fallback
        self.instruction = instruction
        self.timeout = max(2.0, min(30.0, float(timeout)))
        self.budget = JudgeBudget(daily_limit=daily_limit)
        self._cache: dict[str, tuple[str, float]] = {}
        self.stats = {"llm": 0, "cache": 0, "fallback": 0}

    # ------------------------------------------------------------ 缓存
    def _key(self, text: str) -> str:
        body = f"{self.name}|{text.strip()[:MAX_TEXT]}"
        return hashlib.sha1(body.encode("utf-8", "replace")).hexdigest()[:16]

    def _from_cache(self, key: str) -> str:
        item = self._cache.get(key)
        if not item:
            return ""
        value, at = item
        if time.time() - at > CACHE_TTL:
            self._cache.pop(key, None)
            return ""
        return value

    def _to_cache(self, key: str, value: str) -> None:
        if len(self._cache) > 500:  # 简单上限，避免无限增长
            self._cache.clear()
        self._cache[key] = (value, time.time())

    # ------------------------------------------------------------ 解析
    def _parse(self, raw: str) -> str:
        body = str(raw or "").strip()
        if not body:
            raise JudgeError("空回复")
        # 去掉常见包装
        body = re.sub(r"[`\"'“”‘’。，、\s]", "", body)
        for option in self.options:
            if option == body:
                return option
        # 模型多说了几句：找包含的候选词（长词优先，避免「图」吃掉「图片」）
        for option in sorted(self.options, key=len, reverse=True):
            if option in body:
                return option
        raise JudgeError(f"输出不在候选里：{body[:40]}")

    # ------------------------------------------------------------ 判定
    async def judge(self, provider: Any, text: str, *, use_llm: bool = True) -> JudgeResult:
        """判定一段文本。LLM 优先，失败用兜底。永远不抛异常。"""
        body = str(text or "").strip()[:MAX_TEXT]
        if not body:
            self.stats["fallback"] += 1
            return JudgeResult(self.fallback, "fallback", note="空文本")

        key = self._key(body)
        cached = self._from_cache(key)
        if cached:
            self.stats["cache"] += 1
            return JudgeResult(cached, "cache")

        if not use_llm or provider is None or not self.budget.take():
            self.stats["fallback"] += 1
            reason = "关闭" if not use_llm else ("无 provider" if provider is None else "额度用完")
            return JudgeResult(self.fallback, "fallback", note=reason)

        prompt = PROMPT_TEMPLATE.format(
            options=" / ".join(self.options), text=body,
        )
        if self.instruction:
            prompt = f"{self.instruction}\n\n{prompt}"
        # 有些 provider 的 system 用不上，内容已全在 prompt 里
        try:
            import asyncio

            resp = await asyncio.wait_for(provider.text_chat(prompt=prompt), timeout=self.timeout)
        except Exception as exc:
            self.stats["fallback"] += 1
            return JudgeResult(self.fallback, "fallback", note=f"{type(exc).__name__}: {str(exc)[:80]}")

        raw = str(getattr(resp, "completion_text", "") or "")
        if not raw:
            raw = str(getattr(resp, "result", "") or "")
        try:
            value = self._parse(raw)
        except JudgeError as exc:
            self.stats["fallback"] += 1
            return JudgeResult(self.fallback, "fallback", raw=raw[:80], note=str(exc))

        self._to_cache(key, value)
        self.stats["llm"] += 1
        return JudgeResult(value, "llm", raw=raw[:80])

    def cache_clear(self) -> None:
        self._cache.clear()


# ---------------------------------------------------------------- 预置判定器
# 生图：不是「要不要画」，而是「这句话要的是什么」。选项覆盖常见交付物。
IMAGE_KIND = Judge(
    "image_kind",
    options=("画图", "文档", "其他"),
    fallback="其他",
    instruction=(
        "判断用户想让她做什么。\n"
        "画图 = 要一张画面（画/拍/来张图/头像/壁纸/自拍/照片）。\n"
        "文档 = 要一份文件（文档/报告/表格/纪要/清单/Word/Excel/PDF）。\n"
        "其他 = 普通聊天、提问、别的任务。"
    ),
)

# 搜索：是否要联网查
SEARCH_NEED = Judge(
    "search_need",
    options=("要查", "不用"),
    fallback="不用",
    instruction=(
        "判断用户是否需要联网查资料。\n"
        "要查 = 问的是实时/外部事实（价格、新闻、版本、某公司/产品现在的情况）。\n"
        "不用 = 查本地信息（日程、消息、文件）、闲聊、或她能自己回答的。"
    ),
)

# 情绪事件：这句话让她什么感受
EMOTION_EVENT = Judge(
    "emotion_event",
    options=("被骂", "被夸", "被表白", "被撒娇", "被冷落", "被关心", "吵架", "普通"),
    fallback="普通",
    instruction="判断这句话对她的情绪影响，只输出候选里的一个词。",
)

# 撤回：对方是否在说她理解错了
RECALL_NEED = Judge(
    "recall_need",
    options=("要撤回", "不用"),
    fallback="不用",
    instruction=(
        "判断对方是否在说「你刚才理解错了/说错了」。\n"
        "要撤回 = 明确纠正（不是这个意思/我说的是…/你理解错了/重新回答）。\n"
        "不用 = 其他所有情况（包括「不用撤回」「算了」）。"
    ),
)

ALL_JUDGES = {
    "image_kind": IMAGE_KIND,
    "search_need": SEARCH_NEED,
    "emotion_event": EMOTION_EVENT,
    "recall_need": RECALL_NEED,
}


def stats() -> dict[str, dict[str, Any]]:
    """面板用：每个判定器的命中情况。"""
    out: dict[str, dict[str, Any]] = {}
    for name, judge in ALL_JUDGES.items():
        out[name] = {
            "llm": judge.stats["llm"],
            "cache": judge.stats["cache"],
            "fallback": judge.stats["fallback"],
            "left": judge.budget.left(),
            "limit": judge.budget.daily_limit,
        }
    return out
