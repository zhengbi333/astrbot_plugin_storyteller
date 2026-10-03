# alpha-0.88 —— 日程/穿搭「实时调整（像人）」

> 实现第 4 条：对话里出现明确的日程/穿搭安排时，Bot 像人一样决定改不改。
> 按拍板：插件自动检测 + 用模块现有模型（schedule.provider_id / 回退策略）+ 不设频率限制
> （检测门槛本身即闸门，只对"明确的安排"触发，不会每句话都判定）。

## 变更

1. **轻量意图检测** `_detect_plan_intent(text)`：
   - 「穿搭类」：穿什么/穿哪件/换衣服/别穿/换上/衣柜里… → `outfit`；
   - 「日程类」：时间词（明天/下午3点/改到…）+ 安排词（约/陪我去/改成/推迟/取消…）才命中 → `schedule`；
   - **疑问语气不触发**（…吗？/什么安排？/能不能改一下？→ 空），闲聊不触发。
2. **决策提示词** `build_auto_plan_prompt`：给出用户原话 + 今天日程/延误池/未来规划/当前穿着，
   让模型像人一样决定：
   - `add`（排进空档）/ `replace`（更重要→替换对应时段，原安排进延误池）/
     `add_future`（排不进今天→未来规划）/ `reschedule_backlog`（正好补上延误的事）/
     `dress`（改穿搭）/ `none`（闲聊不动作）。
3. **决策执行** `apply_auto_plan`：纯函数落库（ScheduleStore / wardrobe），返回 summary 供日志；
   `main.py` `_auto_plan` 异步触发（失败静默，不阻塞对话；模型不可用则跳过并记 Info）。
4. **配置**：`schedule.auto_manage_enabled`（默认 true）+ 日程页右栏「实时调整（像人）」设置卡。

## 测试

- 新增 `smoke_story_autoplan.py` 23 项：意图检测（命中/疑问不误触/闲聊不触）、
  add/replace（原安排进延误）/add_future/reschedule_backlog/dress/none 落库回读、wardrobe anchor
- 全量回归：takeover 95 / smart 28 / ui_state 14 / intercept 3 / log 10 / verify_045 / propagate /
  scan 0 / verify_057 81 / nav 31
