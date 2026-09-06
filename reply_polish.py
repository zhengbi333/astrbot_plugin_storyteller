"""回复润色：LLM 回复被捕获 → 按模板交给润色模型二次润色与人格校准。

设计要点（独立实现，不与外部插件雷同）：
- 捕获范围：接管直连生成后、接管走主链/放行的主链回复（on_llm_response），统一在此做「回复润色」；
- 模板可编辑（rewrite.template），可用占位符：{回复}{人格}{风格}{状态}{关系}{当前说话}{当前用户}{场合}…；
- 直连润色模型（rewrite.provider_id，留空回退策略），失败/驳回回退原回复；
- RingBuffer 记录「发送给润色 LLM 的内容 / 润色后内容」供页面实时刷新。
"""

from __future__ import annotations

import threading
import time
from typing import Any


class RewriteBuffer:
    """环形缓冲：最近一次回复润色的输入/输出。"""

    def __init__(self, limit: int = 40):
        self._lock = threading.Lock()
        self._limit = max(10, min(200, int(limit)))
        self._items: list[dict[str, Any]] = []

    def record(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._items.append(entry)
            if len(self._items) > self._limit:
                del self._items[: len(self._items) - self._limit]

    def items(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._items[-limit:][::-1])


class ReplyPolisher:
    """回复润色器：把回复按模板交给润色模型二次润色 + 人格校准。"""

    def __init__(self, plugin: Any):
        self._plugin = plugin
        self.buffer = RewriteBuffer(40)

    def _config(self) -> Any:
        return self._plugin.config

    async def polish(self, event: Any, reply_text: str) -> str:
        """润色一条回复：开启且可用则润色，否则/失败回退原回复；并记录输入输出。"""
        raw = str(reply_text or "")
        if not raw.strip():
            return raw
        if not self._config().bool("rewrite.enabled", True):
            return raw
        try:
            from .intercept import replace_template
            from .models import chat_text, resolve_chat_provider

            provider, provider_id = resolve_chat_provider(
                self._plugin.context, self._config(), "rewrite"
            )
            if provider is None:
                return raw
            anchors = self._plugin._anchor_values(event)
            anchors["current_text"] = str(getattr(event, "message_str", "") or "").strip()
            anchors["context"] = self._plugin._recent_timeline_text(
                str(getattr(event, "unified_msg_origin", "") or ""), limit=3
            )
            anchors["reply"] = raw
            # 0.158 空态防御（与接管同源）：润色提示词里"设定/语境"类锚为空时补明确占位，
            # 避免润色模型说"没提身份设定/没说要润色哪句/对方没说什么"而追要
            if not str(anchors.get("current_text") or "").strip():
                anchors["current_text"] = "（对方没有说话）"
            if not str(anchors.get("relationship") or "").strip():
                anchors["relationship"] = "（你和对方目前还不熟悉，保持礼貌与适当距离。）"
            if not str(anchors.get("voice") or "").strip():
                anchors["voice"] = "（尚未设定说话风格——自然、干净地表达即可。）"
            if not str(anchors.get("persona") or "").strip():
                anchors["persona"] = (
                    "（暂无额外角色说明——你就是一位自然、友好、普通的聊天对象。）"
                )
            template = str(self._config().get("rewrite.template", "") or "")
            prompt = replace_template(template, anchors)
            if not prompt.strip():
                return raw
            # 0.158 模板健壮性：模板没有 {回复} 占位符 → 把原文附录在末尾，保证"要润色哪句"永远明确；
            # 模板里有 {回复} 但替换后仍残留（含未闭合写法）→ 模板被写坏，回退原回复不润色
            if "{回复" in prompt and "{回复" in template:
                import logging

                logging.getLogger("astrbot.plugin_storyteller").warning(
                    "[Storyteller] 润色模板占位符未替换（模板可能被改动），回退原回复"
                )
                return raw
            if "{回复}" not in template:
                prompt = prompt.rstrip() + "\n\n请润色下面这句（原文）：\n" + raw
            import logging as _lg

            _lg.getLogger("astrbot.plugin_storyteller").info(
                "[Storyteller] 润色排查(临时): raw_len=%d raw=%s prompt前180=%s",
                len(raw), raw[:100].replace("\n", " "),
                prompt[:180].replace("\n", "⏎"),
            )
            resp = await chat_text(
                provider, self._config(), prompt=prompt, session_id="storyteller_polish",
                _disable_thinking=False,  # 创作类润色：保留模型思考
            )
            self._plugin._record_usage(resp, "rewrite", provider_id or "default")
            polished = str(getattr(resp, "completion_text", "") or "").strip() or raw
            _lg.getLogger("astrbot.plugin_storyteller").info(
                "[Storyteller] 润色排查(临时): polished=%s", polished[:120].replace("\n", " ")
            )
            self.buffer.record(
                {
                    "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                    "session_id": str(getattr(event, "unified_msg_origin", "") or ""),
                    "prompt": prompt[:2000],
                    "raw": raw[:1500],
                    "polished": polished[:1500],
                }
            )
            return polished
        except Exception as exc:
            import logging

            logging.getLogger("astrbot.plugin_storyteller").warning(
                "[Storyteller] 回复润色失败: %s（回退原回复）", exc
            )
            return raw