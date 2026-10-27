"""意图路由：按用户这句话的意图，收窄给模型的工具集。

为什么需要（真机教训）：
她收到「帮我做个 word 文档」时，选了 `story_photo_take`（画图并直接发送，一步到位），
而不是 `toolbox_doc_write`（写完还要再调 send_file）。**描述写得再准，也挡不住"更省事"的工具。**

DSH 的做法是每个工具描述里写清边界；这里再加一层更硬的：**按意图把不该出现的工具直接摘掉**，
让模型没得选。宁可少给工具，也不要它选错。

设计原则：
- 只**收窄**，不新增（不改变默认行为）；
- 关键词保守（宁可漏判，不要误杀正常的"画一张图"）；
- 任何异常都返回原工具集。
"""

from __future__ import annotations

import re
from typing import Any

# 文档类意图：要的是**文件**，不是图片
DOC_INTENT = re.compile(
    # 允许「做个 word」「做份 Word 文档」这类中间带空格/量词的写法
    r"做个?\s*(?:word|Word|WORD|文档|表格|报告|纪要|总结|汇报|简历|说明|清单|方案|计划书)|"
    r"做(?:一)?份\s*(?:word|Word|文档|报告|会议纪要|纪要|总结|汇报|表)|"
    r"写个?\s*(?:word|Word|文档|报告|纪要|总结|汇报|简历)|"
    r"写一?份\s*(?:文档|报告|纪要|总结|汇报)|"
    r"整理成\s*(?:文档|文件|表格|报告)|"
    r"存\s*(?:成|为)\s*(?:文件|文档)|"
    r"导出(?:成)?\s*(?:pdf|PDF|文档|表格)|"
    r"\bword\b|\bdocx\b|\bexcel\b|\bpdf\b",
    re.IGNORECASE,
)

# 文档意图下要摘掉的工具（它们会产出图片/表情，不是文件）
DOC_EXCLUDE = (
    "story_photo_take",     # 画/拍图并直接发送
    "story_emoji_send",     # 发表情包
    "toolbox_image",        # 图片处理
)

# 明确要图/要照片的意图：这时候才允许画图工具
IMAGE_INTENT = re.compile(
    r"画(?:一|个|张|只|幅|下)|拍(?:一|个|张|下)|自拍|照片|图片|头像|壁纸|"
    r"给我看看你|让我看看你|啥样|什么样|长什么样|来张|发张"
)


def _names(tools: list[dict]) -> list[str]:
    out: list[str] = []
    for item in tools or []:
        fn = item.get("function") if isinstance(item, dict) else None
        if isinstance(fn, dict) and fn.get("name"):
            out.append(str(fn["name"]))
    return out


def narrow(text: str, tools: list[dict]) -> tuple[list[dict], str]:
    """按意图收窄工具集。返回 (新工具集, 说明)，说明为空表示没动。"""
    try:
        body = str(text or "").strip()
        if not body or not tools:
            return tools, ""

        wants_doc = bool(DOC_INTENT.search(body))
        wants_image = bool(IMAGE_INTENT.search(body))

        # 既要文档又要图（「写份报告顺便配张图」）→ 不动，让模型自己决定
        if wants_doc and wants_image:
            return tools, ""

        if wants_doc:
            keep = [t for t in tools if (t.get("function") or {}).get("name") not in DOC_EXCLUDE]
            removed = len(tools) - len(keep)
            if removed:
                return keep, f"文档意图：摘掉 {removed} 个产图工具"
            return tools, ""

        return tools, ""
    except Exception:
        return tools, ""
