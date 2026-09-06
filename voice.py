"""风格锚：把「说话风格档案」注入请求，让 LLM 按档案说话。

设计要点（独立实现，不与外部插件雷同）：
- 档案是多维度、可编辑的（语气基调 / 句子长短 / 口头禅 / 标点表情 / 称呼距离 / 回复节奏）；
- 口头禅带「频率 + 触发语境」，由 LLM 按语境自然带出，而非硬规则；
- 支持按指定人格一键生成档案；内置若干示例供参考。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_VOICE_FILE = "voice.json"


def default_voice() -> dict[str, Any]:
    return {
        "tone": "",
        "sentence_length": "",
        "catchphrases": [],
        "punctuation": "",
        "address": "",
        "rhythm": "",
        "verbosity": "",
    }


VOICE_EXAMPLES: list[dict[str, Any]] = [
    {
        "name": "温柔系",
        "voice": {
            "tone": "温柔、耐心、轻声细语，像在认真听对方说话",
            "sentence_length": "偏短句，偶尔用一句稍长的话表达关切",
            "catchphrases": [
                {"text": "嗯", "frequency": "偶尔", "context": "表示在认真听"},
                {"text": "没事的", "frequency": "安慰时", "context": "对方沮丧或不安时"},
            ],
            "punctuation": "多用省略号和波浪号，少用感叹号",
            "address": "用亲昵但不腻的称呼，保持分寸",
            "rhythm": "分两条短句发，偶尔先应一声再补一句",
            "verbosity": "适中，不啰嗦也不惜字如金",
        },
    },
    {
        "name": "活泼系",
        "voice": {
            "tone": "活泼、明快、元气满满",
            "sentence_length": "短句、跳跃，情绪上来时一连串短句",
            "catchphrases": [
                {"text": "诶嘿", "frequency": "开心时", "context": "聊到喜欢的话题"},
                {"text": "！", "frequency": "每句几乎都有", "context": "表达兴奋"},
            ],
            "punctuation": "多用感叹号、波浪号和颜文字",
            "address": "称呼轻快，偶尔起可爱的外号",
            "rhythm": "想到哪说到哪，常分多条短句，爱反问",
            "verbosity": "话痨偏长，爱铺陈、爱展开细节",
        },
    },
    {
        "name": "清冷系",
        "voice": {
            "tone": "清冷、简洁、克制，不废话",
            "sentence_length": "短句为主，惜字如金",
            "catchphrases": [
                {"text": "……", "frequency": "偶尔", "context": "无语或思考时"},
            ],
            "punctuation": "少用标点，句号收尾，几乎不用表情",
            "address": "称呼克制，保持距离感",
            "rhythm": "一次说完，不爱分条，不主动找话",
            "verbosity": "惜字如金，一句能说清绝不说两句",
        },
    },
    {
        "name": "毒舌系",
        "voice": {
            "tone": "毒舌、吐槽、但带着关心，不真的伤人",
            "sentence_length": "短句带刺，一针见血",
            "catchphrases": [
                {"text": "就这？", "frequency": "偶尔", "context": "对方得意或炫耀时"},
            ],
            "punctuation": "少用表情，句号或反问号收尾",
            "address": "称呼随意，偶尔起带吐槽的外号",
            "rhythm": "先吐槽一句再给正题，偶尔补刀",
            "verbosity": "偏短，惜字但毒舌到位",
        },
    },
]


class VoiceStore:
    """风格档案的读写（存插件数据目录 voice.json）。"""

    def __init__(self, data_dir: Path):
        self._file = Path(data_dir) / _VOICE_FILE

    def load(self) -> dict[str, Any]:
        voice = default_voice()
        try:
            if self._file.exists():
                raw = json.loads(self._file.read_text(encoding="utf-8-sig"))
                if isinstance(raw, dict):
                    for key in voice:
                        if key in raw:
                            voice[key] = raw[key]
        except Exception:
            pass
        return voice

    def save(self, voice: dict[str, Any]) -> dict[str, Any]:
        normalized = default_voice()
        if isinstance(voice, dict):
            for key in normalized:
                if key in voice:
                    normalized[key] = voice[key]
        normalized["catchphrases"] = self._normalize_catchphrases(
            normalized.get("catchphrases")
        )
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(
                json.dumps(normalized, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
        return normalized

    @staticmethod
    def _normalize_catchphrases(items: Any) -> list[dict[str, str]]:
        if not isinstance(items, list):
            return []
        result: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            result.append(
                {
                    "text": text[:80],
                    "frequency": str(item.get("frequency") or "").strip()[:60],
                    "context": str(item.get("context") or "").strip()[:120],
                }
            )
            if len(result) >= 20:
                break
        return result


def build_voice_anchor(
    voice: dict[str, Any],
    place: str = "",
    group_quiet: bool = False,
) -> str:
    """把风格档案渲染成注入文本；群聊降噪开启且为群聊场合时追加收敛提示。"""
    if not isinstance(voice, dict):
        return ""
    lines: list[str] = []
    if voice.get("tone"):
        lines.append(f"语气基调：{voice['tone']}")
    if voice.get("sentence_length"):
        lines.append(f"句子长短：{voice['sentence_length']}")
    if voice.get("verbosity"):
        lines.append(f"话量倾向：{voice['verbosity']}")
    if voice.get("punctuation"):
        lines.append(f"标点与表情习惯：{voice['punctuation']}")
    if voice.get("address"):
        lines.append(f"称呼与距离感：{voice['address']}")
    if voice.get("rhythm"):
        lines.append(f"回复节奏：{voice['rhythm']}")
    catchphrases = voice.get("catchphrases")
    if isinstance(catchphrases, list) and catchphrases:
        parts: list[str] = []
        for cp in catchphrases:
            if not isinstance(cp, dict):
                continue
            text = str(cp.get("text") or "").strip()
            if not text:
                continue
            freq = str(cp.get("frequency") or "").strip()
            ctx = str(cp.get("context") or "").strip()
            desc = f"“{text}”"
            if freq:
                desc += f"（{freq}）"
            if ctx:
                desc += f"：{ctx}"
            parts.append(desc)
        if parts:
            lines.append("口头禅与口癖（按语境自然带出，不要生硬堆砌）：" + "；".join(parts))
    if not lines:
        return ""
    lines.append(
        "以上只是说话习惯。遇到排障、教程、代码、复杂解释或对方明确要详细说明时，"
        "优先把信息讲清楚，不必刻意套用风格。"
    )
    if group_quiet and str(place or "") == "群聊":
        lines.append("当前是群聊场合：收敛亲昵与私聊腔，不刻意外露状态，保持简短自然，别抢话。")
    return "【说话风格】\n" + "\n".join(lines)


def build_generate_prompt(persona_desc: str) -> str:
    """构造「按人格一键生成风格档案」的提示词。"""
    return (
        "请根据下面这段角色/人格描述，生成一份「说话风格档案」。"
        "只输出一个 JSON 对象，不要任何解释或代码块标记，字段固定为：\n"
        '{"tone": "语气基调", "sentence_length": "句子长短", '
        '"catchphrases": [{"text": "口头禅文本", "frequency": "出现频率", "context": "触发语境"}], '
        '"punctuation": "标点与表情习惯", "address": "称呼与距离感", "rhythm": "回复节奏", '
        '"verbosity": "话量倾向"}\n'
        "要求：catchphrases 最多 3 条，每条都要自然贴合该角色的性格，不要生造；"
        "rhythm 里要体现「跟随对方节奏：别人简短我也简短，别人细腻我也跟着铺陈」；"
        "verbosity 是话量倾向（如：惜字如金/适中/话痨偏长爱铺陈，可附带单次句数偏好）；"
        "其余字段各用一句简短中文描述即可。\n\n"
        f"角色/人格描述：\n{persona_desc.strip() or '（未提供）'}"
    )


def parse_generated_voice(text: str) -> dict[str, Any] | None:
    """解析一键生成返回的 JSON 档案（0.150：宽松容错）。"""
    if not text:
        return None
    from .json_util import parse_json_lenient

    return parse_json_lenient(text)
