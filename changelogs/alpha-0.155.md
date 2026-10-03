# alpha-0.155

## 命令消息不再触发「刚聊完」冷却（用户反馈：只发了 /reset 也被顺延 30 分钟）

- **根因**：消息观察层对**任何**消息都记录 `note_interaction`（刚聊完冷却 / 未回应状态），`/reset`、`/help` 等命令消息也被当成「聊过」→ 主动对话被 `cooldown_after_chat_minutes`(30 分钟) 顺延,哪怕用户根本没聊。
- **修复**：`note_interaction` 开头跳过命令消息（复用防抖的 `_looks_command` 判定,含 CQ/@/引用剥离后的判断）——命令消息:
  - 不更新「刚聊完」冷却（试发预览不再误报"刚聊完 30 分钟内不打扰"）;
  - 不算回应、不清未回应计数（streak 保留）。
- **回归**：smoke_proactive_dynamic **30 项**（+3 命令豁免断言:普通消息记录 / /reset 不记录 / 命令不清 streak）;interact 51、057 169、41 冒烟 0 失败。