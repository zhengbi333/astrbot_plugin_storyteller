"""人格注入体：把 AstrBot 人格/设定整理成一份可直接注入提示词的「{人格}」文本。

设计要点（独立实现，不与外部插件雷同）：
- 与风格模块分工：风格=说话方式（六/七维档案），「人格」=身份背景（叫什么、身份、世界观等）；
- 一键生成：选 AstrBot 人格库人格（或手填），交由「人格生成模型」直连生成注入体并自动保存；
- 注入 {人格} 时：优先用已保存的注入体；为空时兜底 AstrBot 当前默认人格 prompt（在接管路径异步读取）；
- 生成后仍可手动编辑（textarea）与重新生成。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_PERSONA_FILE = "persona_injection.json"


class PersonaStore:
    """人格注入体的读写（存插件数据目录 persona_injection.json）。"""

    def __init__(self, data_dir: Path):
        self._file = Path(data_dir) / _PERSONA_FILE
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            if self._file.exists():
                raw = json.loads(self._file.read_text(encoding="utf-8-sig"))
                if isinstance(raw, dict):
                    return {"text": str(raw.get("text", "") or "")[:4000]}
        except Exception:
            pass
        return {"text": ""}

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def load(self) -> dict[str, Any]:
        return dict(self._data)

    def save(self, text: str) -> dict[str, Any]:
        self._data["text"] = str(text or "").strip()[:4000]
        self._data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        self._save()
        return dict(self._data)

    def injection_text(self) -> str:
        return str(self._data.get("text", "") or "").strip()


def build_persona_generate_prompt(persona_desc: str) -> str:
    """构造「按人格描述生成人格注入体」的提示词（直接输出正文，非 JSON）。"""
    return (
        "请根据下面这段角色/人格描述，生成一份「人格注入体」——即发送给对话 LLM 的提示词里的"
        "【你的身份】段落。只输出这段正文本身，不要任何解释、JSON 或代码块标记。\n"
        "内容应尽量完整覆盖（描述里有的就按其原意保留，缺的不要凭空编造）：\n"
        "- 你的名字与别人如何称呼你；\n"
        "- 你的身份设定（你是谁、在做什么、与对方是什么关系语境）；\n"
        "- 身世/背景、世界观；\n"
        "- 性格气质、信念好恶、说话立场与边界；\n"
        "- 让模型能凭这段完整地扮演该人格（不要代入系统或插件身份，不要说自己是 AI/模型/助手）。\n\n"
        f"角色/人格描述：\n{persona_desc.strip() or '（未提供）'}"
    )