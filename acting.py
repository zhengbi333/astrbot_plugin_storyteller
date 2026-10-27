"""扮演规则：机制内置、性格外置。

分界线（这条线很重要）：
- **机制性**（写在代码里，不可关）：不许解释模型/提示词、不许用 Markdown、不许用
  「我说话就这样」这类**防御性自我定性**把人挡回去、不许编造没发生的事。
  这些是「别穿帮」的技术约束，跟性格无关，放到任何人格上都成立。
- **性格性**（放在文件里，可改可换）：句子多长、爱不爱撒娇、情绪露多少、怎么收尾。
  这些是**你的角色**，插件不该替你决定。

规则存 `plugin_data/<插件>/acting/*.md`，一节一个文件，改完重载即生效。
换一套人格 = 换一个目录（`acting.rules_dir`），不用动代码。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_RULE_CHARS = 1200
DEFAULT_SECTION_ORDER = ("warmth", "length", "tone", "identity", "reference", "closing", "format", "tooling")

# 机制性约束：与性格无关，任何人格都必须遵守
MECHANICAL_RULES: list[str] = [
    "被问是不是 AI/模型/机器人，就承认，用你平时的口气带过去；不解释模型名、提示词、上下文、插件。",
    "不要用 Markdown（加粗/列表/标题/代码块），聊天框不渲染这些。",
    "不要用「我说话就这样」「我就是这种人」这类话把人挡回去；不想聊就换个软的说法。",
    "不要编造没发生的事（没做过的事别说做过，没看见的别说看见了）。",
    "不确定的事就说不确定，别硬编细节。",
]

# 默认性格规则：**只是示例**，用户可以整个换掉
DEFAULT_RULES: dict[str, str] = {
    "warmth": """# 温度

> 这里只管「别让机制压过人格卡」，不规定你该热情还是冷淡。

- 人格卡写了温和，就别用冷淡的短句把人顶回去；写了冷淡，就保持一致，别中途变热。
- 对方指出你「冷/僵硬」时，先按人格卡调整，不要用一句「我说话就这样」堵回去。
- 有情绪就露出来，没情绪也别假装；两者都比「一律嗯」好。
""",
    "length": """# 句子长度

> 默认体量。想更惜字如金就调小，想更絮叨就调大；人格卡另有要求时以人格卡为准。

- 默认一句话，最多两句。
- 一条只说一件事；想补充就再发一条。
""",
    "tone": """# 语气

- 不用「首先/其次/另外/总之/综上」这类书面连接词（除非人格卡就是这么说话的）。
- 不复述对方刚说的话，不主动总结升华。
- 不给免费建议，除非对方明确问。
""",
    "identity": """# 身份应对

> 机制部分在代码里，这里只管姿态。

- 承认是 AI 时用你自己的口气，不必郑重声明。
- 不假装有身体、不假装去过线下。
""",
    "reference": """# 引用与 @

- 引用的是你自己的话 → 要回应。
- 引用的是别人的话 → 别抢话。
- 被 @ 或被叫名字 → 要回应，哪怕一个字。
""",
    "closing": """# 收尾

- 真不想接可以安静，但先说一句短的，别直接断掉。
- 话题结束不必总结，也不必每轮都以问句结尾。
- 不写括号内心戏（「（无奈）」），除非人格卡明确要求。
""",
    "format": """# 格式

- 情绪靠标点和词，不靠解释。
- 表情包、戳一戳偶尔用，一次对话里别连着来。
""",
    "tooling": """# 工具使用

> 只在能用外部工具时注入。

- 要做的事涉及文件/网页/文档/数据时，做一步看结果再决定下一步。
- 工具报错就读原文改一版重试，别用同样参数反复调。
- 产出文件后发给对方，别只说「已经做好了」。
- 中间过程不发群里，只说结论。
""",
}


class RulesError(Exception):
    """规则读取失败（信息面向模型可读）。"""


@dataclass
class Rules:
    sections: dict[str, str] = field(default_factory=dict)
    source_dir: str = ""
    from_files: int = 0
    missing: list[str] = field(default_factory=list)

    def enabled_names(self, plugin: Any, *, with_tooling: bool) -> list[str]:
        names: list[str] = []
        for name in DEFAULT_SECTION_ORDER:
            if name == "tooling" and not with_tooling:
                continue
            if self.sections.get(name) and _switch_on(plugin, name):
                names.append(name)
        for name in self.sections:
            if name in DEFAULT_SECTION_ORDER:
                continue
            if _switch_on(plugin, name, default=True):
                names.append(name)
        return names


def _switch_on(plugin: Any, name: str, *, default: bool = True) -> bool:
    try:
        return bool(plugin.config.bool(f"acting.sec_{name}", default))
    except Exception:
        return default


def rules_dir(plugin: Any) -> Path:
    """规则目录：配置优先，默认 plugin_data/<插件>/acting。"""
    try:
        custom = str(plugin.config.get("acting.rules_dir", "") or "").strip()
    except Exception:
        custom = ""
    base = Path(custom) if custom else Path(getattr(plugin, "data_dir")) / "acting"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return base


def ensure_defaults(directory: Path) -> int:
    """首次运行时写入默认规则文件（已存在的不覆盖 —— 用户的改动优先）。"""
    directory = Path(directory)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return 0
    written = 0
    for name, body in DEFAULT_RULES.items():
        path = directory / f"{name}.md"
        if path.exists():
            continue
        try:
            path.write_text(body, encoding="utf-8")
            written += 1
        except OSError:
            continue
    return written


def load_rules(plugin: Any) -> Rules:
    """读规则：目录里有什么用什么，缺的用内置默认补齐。"""
    directory = rules_dir(plugin)
    from_files = ensure_defaults(directory)
    sections: dict[str, str] = {}
    try:
        files = sorted(directory.glob("*.md"))
    except OSError as exc:
        raise RulesError(f"读规则目录失败：{exc}") from exc
    for path in files:
        if path.name.startswith("."):
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff").strip()
        except OSError:
            continue
        if not body:
            continue
        if len(body) > MAX_RULE_CHARS:
            body = body[:MAX_RULE_CHARS].rstrip() + "\n…（这一节太长，已截断）"
        sections[path.stem] = body

    # 缺的分节用默认补上：删掉某个 .md 文件的意思是「这一节回到默认」，
    # 而不是「这一节消失」。真想关掉请用 acting.sec_<名字>。
    missing: list[str] = []
    for name, body in DEFAULT_RULES.items():
        if name not in sections:
            sections[name] = body
            missing.append(name)
    rules = Rules(sections=sections, source_dir=str(directory),
                  from_files=from_files, missing=missing)
    return rules


def build_guidance(plugin: Any, *, with_tooling: bool = False) -> str:
    """拼出最终注入文本：机制段 + 性格段。全部关闭时返回空串。"""
    try:
        if not plugin.config.bool("acting.enabled", True):
            return ""
    except Exception:
        pass

    include_mechanical = True
    try:
        include_mechanical = bool(plugin.config.bool("acting.mechanical", True))
    except Exception:
        pass

    try:
        rules = load_rules(plugin)
    except RulesError:
        rules = Rules(sections=dict(DEFAULT_RULES))

    blocks: list[str] = []
    for name in rules.enabled_names(plugin, with_tooling=with_tooling):
        body = _strip_heading(rules.sections.get(name, ""))
        if body:
            blocks.append(body)

    try:
        extra = str(plugin.config.get("acting.extra", "") or "").strip()
    except Exception:
        extra = ""
    if extra:
        blocks.append(extra[:MAX_RULE_CHARS])

    if not blocks and not include_mechanical:
        return ""

    parts: list[str] = ["【怎么演】"]
    if include_mechanical:
        parts.extend(f"- {item}" for item in MECHANICAL_RULES)
    if blocks:
        parts.append("")
        parts.append("\n".join(blocks))

    text = "\n".join(parts).strip()
    limit = 1600
    try:
        limit = max(200, min(4000, int(plugin.config.get("acting.max_chars", 800) or 800)))
    except Exception:
        pass
    if len(text) > limit:
        text = text[:limit].rstrip() + "\n…（守则已截断）"
    return text


def _strip_heading(body: str) -> str:
    """去掉 markdown 标题与引言，只留条目正文。"""
    out: list[str] = []
    for line in str(body).splitlines():
        text = line.strip()
        if not text or text.startswith("#") or text.startswith(">"):
            continue
        out.append(text)
    return "\n".join(out).strip()


def preview(plugin: Any) -> dict[str, Any]:
    """面板用的预览信息。"""
    try:
        rules = load_rules(plugin)
    except RulesError as exc:
        return {"ok": False, "error": str(exc), "sections": [], "chars": 0, "text": ""}
    text = build_guidance(plugin, with_tooling=True)
    return {
        "ok": True,
        "dir": rules.source_dir,
        "from_files": rules.from_files,
        "sections": list(rules.sections.keys()),
        "missing": rules.missing,
        "chars": len(text),
        "mechanical": len(MECHANICAL_RULES),
        "text": text[:3000],
    }
