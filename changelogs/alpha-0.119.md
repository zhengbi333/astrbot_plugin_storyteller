# alpha-0.119

## 主动页布局重新分配（右栏设置过长）

0.118 后主动设置达 13 项全挤右栏 300px，过长。重排三栏：

- **左栏**：已发送消息 / 目标用户 /「未回应动态与心情」（6 项：mood_link、mood_down_streak、unanswered_slowdown_start、unanswered_max_interval_multiplier、silent_after_streak、silent_after_hours）。
- **中栏**：候选判定记录 / 报错汇报台 /「主动模板与发送预览」（占位符提示 + textarea + 保存 + 完整提示词查看合并一卡；模板编辑放宽栏更舒适）。
- **右栏**：「主动设置 · 节奏与边界」（8 项：provider_id、min/max_interval_hours、max_daily、quiet_hours、cooldown_after_chat_minutes、session_platform、archive_history；顺带补上此前模块页未渲染的「刚聊完顺延」）。

事件绑定（pro-template / pro-prompt-view / pro-prompt-out）按 id 查找，不受栏位移动影响。

## 测试

- verify_057 主动页新增布局断言：未回应设置在左栏、模板在中栏、节奏与边界在右栏（按 HTML 顺序校验）→ 97 项全绿。