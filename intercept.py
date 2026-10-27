"""LLM 请求拦截记录 + 最近发送给对话模型的请求快照。

设计要点（独立实现，不与外部插件雷同）：
- InterceptBuffer：拦截时抓到的原始请求与用户消息（环形缓冲，供「拦＆改」左侧展示）；
- SentRequestBuffer：**最终发送给对话用 LLM 的内容快照**（不区分模式）——
  放行模式的注入后请求、接管模式的模板组装结果、监视模式的原始请求、阻断模式的被拦截内容，
  供「拦＆改」右下实时面板展示最近发给 LLM 的是什么；
- 拦截模式枚举与「拦＆改」模板占位符清单集中在此，保证前后端口径一致。
"""

from __future__ import annotations

import threading
import time
from typing import Any


class InterceptBuffer:
    """线程安全的环形缓冲，保存最近的拦截记录（请求与用户消息各一条链）。"""

    def __init__(self, limit: int = 50):
        self._lock = threading.Lock()
        self._limit = max(1, min(200, int(limit)))
        self._llm_requests: list[dict[str, Any]] = []
        self._user_requests: list[dict[str, Any]] = []

    def resize(self, limit: int) -> None:
        self._limit = max(1, min(200, int(limit)))
        with self._lock:
            self._llm_requests = self._llm_requests[-self._limit :]
            self._user_requests = self._user_requests[-self._limit :]

    def record_llm_request(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._llm_requests.append(entry)
            if len(self._llm_requests) > self._limit:
                del self._llm_requests[: len(self._llm_requests) - self._limit]

    def record_user_request(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._user_requests.append(entry)
            if len(self._user_requests) > self._limit:
                del self._user_requests[: len(self._user_requests) - self._limit]

    def llm_requests(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._llm_requests[-limit:][::-1])

    def user_requests(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._user_requests[-limit:][::-1])

    def clear(self) -> None:
        with self._lock:
            self._llm_requests.clear()
            self._user_requests.clear()


class SentRequestBuffer:
    """最终发送给对话用 LLM 的请求快照（环形缓冲，最新在前，供面板实时展示）。"""

    def __init__(self, limit: int = 30):
        self._lock = threading.Lock()
        self._limit = max(1, min(100, int(limit)))
        self._sent: list[dict[str, Any]] = []

    def record_sent(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._sent.append(entry)
            if len(self._sent) > self._limit:
                del self._sent[: len(self._sent) - self._limit]

    def sent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._sent[-limit:][::-1])

    def clear(self) -> None:
        with self._lock:
            self._sent.clear()


def utc_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


# ---------------------------------------------------------------- 拦截模式

# 拦截模式（配置值即中文显示值，前端下拉选择）
MODE_MONITOR = "监视"      # 什么都不管只监视：记录，不注入不阻断，主链原样发送
MODE_PASS = "放行"         # 拦截并注入（五锚+记忆等）后放行主链
MODE_BLOCK = "阻断"        # 拦截阻断：记录并静默（不发送 LLM）
MODE_TAKEOVER = "接管改换"  # 拦截后按模板组装提示词，直连接管模型生成回复并发送
MODE_TAKEOVER_MAINCHAIN = "接管走主链"  # 拦截后把模板写进主链即将发给 LLM 的请求并放行（回复走主链管线）

ALL_MODES = [MODE_MONITOR, MODE_PASS, MODE_BLOCK, MODE_TAKEOVER, MODE_TAKEOVER_MAINCHAIN]


def resolve_mode(raw_value: Any) -> str:
    """把配置里的模式值规范化为合法模式；非法/空回退「接管走主链」（0.148 起默认介入方式，最温和且零插件冲突）。"""
    value = str(raw_value or "").strip()
    if value in ALL_MODES:
        return value
    return MODE_TAKEOVER_MAINCHAIN


# ---------------------------------------------------------------- 模板占位符

# 模板占位符清单：key=配置/注入键，value=模板里书写的占位符（与前端 chips 一致）
TEMPLATE_PLACEHOLDERS: dict[str, str] = {
    "persona": "{人格}",
    "context": "{上下文}",
    "current_text": "{当前说话}",
    "current_user": "{当前用户}",
    "place": "{场合}",
    "identity": "{身份}",
    "relationship": "{关系}",
    "voice": "{风格}",
    "presence": "{状态}",
    "inner": "{思绪}",
    "schedule": "{日程}",
    "wardrobe": "{穿搭}",
    "memory": "{记忆}",
    "weather": "{天气}",
    "mind": "{见闻}",
    "image_wish": "{生图意愿}",
    "search_result": "{搜索结果}",
    "time": "{时间}",
    "reply": "{回复}",
    "acting": "{守则}",
}

# 占位符作用域：只对**特定模板**有意义的占位符（其余两个模板都有效）。
# `reply` = 待润色的那段原文，**只有润色链路会给它赋值**（reply_polish.py: anchors["reply"] = raw），
# 在「拦和改」模板里它恒被替换为空字符串 —— 前端据此把它标灰并给出说明，避免误用。
PLACEHOLDER_SCOPES: dict[str, str] = {
    "reply": "polish",
}

# 占位符显示顺序（前端 chips 与后端替换同序；人格/当前对话在前，各模块锚在后，回复内容最后）
TEMPLATE_ORDER = [
    "persona", "context", "current_text", "current_user", "place", "identity",
    "relationship", "voice", "presence", "inner", "schedule", "wardrobe", "memory",
    "weather", "mind", "image_wish", "search_result", "time", "reply",
]

DEFAULT_TEMPLATE = (
    "【你的身份】（AstrBot 人格/设定）\n"
    "{人格}\n\n"
    "【当前对话对象与场合】\n"
    "当前和你对话的人：{当前用户}\n"
    "发送场合：{场合}\n\n"
    "【本次对话上下文】\n"
    "{上下文}\n\n"
    "【对方刚刚说的话】\n"
    "{当前说话}\n\n"
    "【你是「为你续写的故事」里的角色，以下是此刻的你】\n"
    "{身份}\n"
    "{关系}\n"
    "{风格}\n"
    "{状态}\n"
    "{思绪}\n"
    "{日程}\n"
    "{穿搭}\n"
    "{记忆}\n"
    "{天气}\n"
    "{见闻}\n"
    "{生图意愿}\n"
    "{搜索结果}\n"
    "当前时间：{时间}\n\n"
    "请以这个角色的身份，基于本次对话上下文，自然回应对方刚刚说的话；不要提任何系统机制。"
)

# 0.184 迁移：旧版本默认模板（11 个占位符，被用户保存进配置后新默认不生效）；
# 加载时若配置值仍等于它，自动升级为新完整模板（17 个占位符全应用）。
# 0.240：除 0.184 那个旧串外，schema 里长期挂着另一版默认（11 个占位符）——
# AstrBot 会用 schema 默认值补齐配置，于是**新装机拿到的就是那一版**，代码里的完整默认从未生效。
# 这里一并登记，加载时若配置值与其中任一完全一致，就升级为当前完整默认（自定义过的不动）。
LEGACY_DEFAULT_TEMPLATES: tuple[str, ...] = ()


LEGACY_DEFAULT_TEMPLATE = (
    "【本次对话上下文】\n"
    "{上下文}\n\n"
    "【对方刚刚说的话】\n"
    "{当前说话}\n\n"
    "【你是「为你续写的故事」里的角色，以下是此刻的你】\n"
    "{身份}\n"
    "{关系}\n"
    "{风格}\n"
    "{状态}\n"
    "{思绪}\n"
    "{日程}\n"
    "{记忆}\n"
    "{天气}\n"
    "{见闻}\n"
    "当前时间：{时间}\n\n"
    "请以这个角色的身份，基于本次对话上下文，自然回应对方刚刚说的话；不要提任何系统机制。"
)


# 0.240：曾被长期挂在 _conf_schema.json 里的那版拦截模板默认值（11 个占位符）。
# AstrBot 会用 schema 默认值补齐配置，因此**新装机拿到的正是这一版**——
# 它是"默认模板没全用上"的直接原因。这里**冻结**历史原文以便识别旧值；
# 不要改成"从 schema 读"：schema 已同步为新默认，那样就认不出旧串了。
SCHEMA_LEGACY_DEFAULT_TEMPLATE = (
    "【本次对话上下文】\n"
    "{上下文}\n\n"
    "【对方刚刚说的话】\n"
    "{当前说话}\n\n"
    "【你是「为你续写的故事」里的角色，以下是此刻的你】\n"
    "{身份}\n"
    "{关系}\n"
    "{风格}\n"
    "{状态}\n"
    "{日程}\n"
    "{记忆}\n"
    "{天气}\n"
    "{见闻}\n"
    "当前时间：{时间}\n\n"
    "请以这个角色的身份，基于本次对话上下文，自然回应对方刚刚说的话；不要提任何系统机制。"
)


def fillable_placeholder_keys(mode: str) -> set[str]:
    """某条链路**真正会赋值**的占位符 key 集合（供自检用：默认模板只能引用这些）。

    - 两条链路都基于 `main._anchor_values`（各模块锚）；
    - 接管（reply）另外补 current_text / context / inner；
    - 润色（polish）另外补 current_text / context / reply。
    """
    base = {
        "persona", "current_user", "place", "identity", "voice", "presence", "schedule",
        "wardrobe", "memory", "weather", "mind", "image_wish", "search_result", "time",
        "relationship",
    }
    if mode == "polish":
        return base | {"current_text", "context", "reply"}
    return base | {"current_text", "context", "inner"}


def placeholder_list() -> list[dict[str, str]]:
    """占位符清单（供前端渲染 chips）；`scope` 非空表示只在对应模板有效。"""
    return [
        {
            "key": key,
            "placeholder": TEMPLATE_PLACEHOLDERS[key],
            "label": key,
            "scope": PLACEHOLDER_SCOPES.get(key, ""),
        }
        for key in TEMPLATE_ORDER
    ]


def template_placeholder_of(key: str) -> str:
    return TEMPLATE_PLACEHOLDERS.get(key, "")


# 0.240：旧默认串清单（模块加载后补齐）——LEGACY_DEFAULT_TEMPLATE（0.184 前）+
# schema 里那版 11 个占位符的默认值（新装机实际拿到的那一版）
LEGACY_DEFAULT_TEMPLATES = tuple(
    x for x in {LEGACY_DEFAULT_TEMPLATE, SCHEMA_LEGACY_DEFAULT_TEMPLATE} if x
)


def is_legacy_default_template(value: str) -> bool:
    """配置里的模板是否等于「某个历史默认值」（完全一致才算，避免覆盖用户自定义）。"""
    text = str(value or "").strip()
    if not text:
        return False
    return any(text == str(item or "").strip() for item in LEGACY_DEFAULT_TEMPLATES)


def replace_template(template: str, values: dict[str, str]) -> str:
    """把模板里的全部占位符替换为对应内容（缺失/空内容替换为空串）。"""
    text = template or ""
    for key in TEMPLATE_ORDER:
        placeholder = TEMPLATE_PLACEHOLDERS.get(key, "")
        if not placeholder:
            continue
        content = str(values.get(key) or "").strip()
        text = text.replace(placeholder, content)
    return text.strip()