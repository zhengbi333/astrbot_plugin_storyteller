# alpha-0.31（2026-08-08）

## 变更

- **修复防抖结算后无回复**：
  - 根因：窗口内消息被静默时设置了 `should_call_llm(True)`（禁止默认 LLM 请求）与 `stop_event`；
    结算时只调用了 `continue_event()`（清除停止标志），**未清除禁止 LLM 的标志**——
    锚事件恢复传播后主链仍因 `call_llm=True` 跳过请求，表现为「合并发送后无任何回复」；
  - 修复：结算恢复锚事件时同时调用 `should_call_llm(False)`（恢复默认 LLM 请求），
    合并内容正常送主链并回复。

## 说明

- 版本备份：工作区 backup 目录下的 `astrbot_plugin_storyteller_alpha-0.31`。
