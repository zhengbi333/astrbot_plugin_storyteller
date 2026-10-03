# alpha-0.60 —— Bug 修复（接管兼容 / 表情包渲染 / 兜底 / 清理）

> 自查发现的缺陷修复 + 版本迭代。未新增功能。

## 修复

- **接管改换兼容 `text_chat` 的 `system_prompt` 形参**：部分 AstrBot/provider 版本的 `text_chat` 不接受 `system_prompt`
  命名参数，原先会导致 `TypeError` 被吞、接管永久静默。现在先用 `inspect.signature` 探测：
  - 支持 → 照常传 `system_prompt`（模板作为系统提示词）；
  - 不支持 → 把模板内容并入 `prompt` 头部发送，接管功能照常工作。
- **接管 Mode 表情包占位符渲染**：接管是插件直连生成，之前绕过主链导致 `on_llm_response`（表情包/二次润色）
  不触发，回复里的 `[emoji:xx]` 占位符会原样发给用户。现在发送前用 `emoji_store.render()` 把占位符渲染为
  「文本 + 图片」链（与主链处理一致）；无 `emoji_store` 时安全降级为纯文本。
- **主链拦截异常兜底 stop**：`on_llm_request` 外层异常时，若正处于「接管改换 / 阻断」模式也尝试 `stop_event()`，
  避免极端情况下退化为未接管的普通回复。
- **清理死代码**：`on_llm_request` 未使用的 `replace_template` 导入、前端 `buildTemplateChips` 无用变量。

## 测试

- `smoke_story_takeover.py` 47 项（新增：旧式签名探测与 prompt 前缀降级、无表情包占位渲染、表情包占位渲染为文本+图片链）
- 全套回归：ui_state 14 / intercept 3 / smart 22 / log 10 / takeover 47 / nav 35 / pages 35 / verify_045 / propagate / 语法 / 雷同 0
