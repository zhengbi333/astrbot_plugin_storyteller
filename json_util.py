# -*- coding: utf-8 -*-
"""宽松 JSON 解析（0.150：平台/模型差异容错）。

模型输出偶带 markdown 围栏、说明文字、尾部逗号等，不同平台/模型格式不一。
统一解析入口：剥围栏 → 直接解析 → 提取外花括号 → 修尾逗号；全部失败返回 None，
由调用方记录原始输出（便于诊断具体平台差异）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from .log import logger


def _try_load(candidate: str) -> Any:
    try:
        return json.loads(candidate)
    except Exception:
        return _MISSING


_MISSING = object()


def _fix_missing_quotes(text: str) -> str:
    """0.178：修复「引号缺失」畸形（模型偶发，非聚合问题）。

    已观测两类：
    1) 字符串值缺闭合引号：{"end": "07:30, "activity"... → "07:30",
    2) 键缺前引号：[start": "00:00" → [{"start": "00:00"（0.176 聚合已修；
       模型侧偶发仍会出现，这里兜底）。
    只作用于「显然畸形」的位置，合法 JSON 不受影响（断言精确限定）。
    """
    t = str(text or "")
    # 1) 值缺后引号：值（时间/短词）后直接跟逗号或右括号
    t = re.sub(r'(?<=")([0-9]{1,2}:[0-9]{2}|[A-Za-z_][A-Za-z0-9_ ]{0,20})(?=\s*[,}\]])', r'\1"', t)
    # 2) 键缺前引号：（[ 或 , 后直接是 单词"（如 [start": "00:00"）
    t = re.sub(r'([\[,]\s*)([A-Za-z_][A-Za-z0-9_]*)"\s*:', r'\1"\2":', t)
    return t


def parse_json_lenient(text: str) -> Any | None:
    """宽松解析 JSON 对象/数组；无法解析返回 None。

    0.173 增强：常规失败后做「尾截断前缀扫描」——模型输出可能被令牌上限截断
    （尾部残缺），从候选中逐步去掉尾部再尝试（每步 16 字符，最多 48 步 ≈ 768 字符）；
    取到能解析的前缀即返回（末尾残缺的条目由调用方校验兜底）。
    """
    raw = str(text or "").strip()
    if not raw:
        return None
    candidates: list[str] = [raw]
    # 1) markdown 代码围栏
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if m:
        candidates.append(m.group(1).strip())
    # 2) 第一个 { 到最后一个 }（跳过前言/后记）
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        candidates.append(raw[start : end + 1])
    # 3) 修尾部逗号（,} / ,]）
    for candidate in candidates:
        value = _try_load(candidate)
        if value is not _MISSING:
            return value
    for candidate in candidates:
        fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
        if fixed != candidate:
            value = _try_load(fixed)
            if value is not _MISSING:
                return value
    # 3.5) 缺失引号修复（0.178 声明、0.188 真正接入——此前只定义了函数，从未调用；
    #      缺引号畸形（"07:30,）一直靠「失败重试」兜底，浪费一次调用）
    for candidate in candidates:
        fixed = _fix_missing_quotes(candidate)
        if fixed != candidate:
            value = _try_load(fixed)
            if value is not _MISSING:
                return value
            fixed2 = re.sub(r",\s*([}\]])", r"\1", fixed)
            if fixed2 != fixed:
                value = _try_load(fixed2)
                if value is not _MISSING:
                    return value
    # 4) 尾截断修复（0.173）：按完整对象/数组边界切前缀 + 补闭合（模型被截断常缺 ]} ）
    for candidate in candidates:
        idxs = [m.start() for m in re.finditer(r"[}\]]", candidate)]
        for idx in reversed(idxs):
            prefix = candidate[: idx + 1].rstrip()
            for tail in ("", "]", "}]"):
                for t in (prefix + tail, prefix + tail + "}"):
                    value = _try_load(t)
                    if value is not _MISSING:
                        return value
    return None


def parse_json_lenient_logged(text: str, what: str) -> Any | None:
    """解析失败时记录原始输出的前 240 字（供用户反馈平台差异格式）。"""
    value = parse_json_lenient(text)
    if value is None:
        preview = re.sub(r"\s+", " ", str(text or ""))[:240]
        logger.warning("[Storyteller] %s 解析失败，原始输出（前 240 字）: %s", what, preview)
    return value