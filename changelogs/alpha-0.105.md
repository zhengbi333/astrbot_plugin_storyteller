# alpha-0.105（主动对话页重构）

按用户拍板：三栏（发送/候选/用户卡）+ 四个新能力 + 接入梦余波取材。

## 后端

- **梦余波取材**：`_collect_context` 增加 `dream`/`dream_aftermath`；`_build_prompt` 若昨夜噩梦则提示
  "心里还留着点不安，想跟对方说说的念头更强"（甜梦则暖意）；候选 sources 新增 `dream` 路。
- **发送历史**：`_record_sent`（最近 60 条，user/text/at）＋ `/proactive/status` 返回 `sent_history`。
- **每用户详情**：per_user 增加 `today_sent`（今日该用户已发数）、`last_interaction`（最近回应时间）。
- **试发预览路由**：`POST proactive/preview`——调用 `_should_send` + `_collect_context` + `_generate`，
  生成一条但**不发送**，返回 should_send/reason/sources/text（前端展示）。
- 候选记录上限 30→60；`_daily_per_user` 记录按用户今日计数。

## 前端（三栏）

- **左栏**：已发送消息时间线（条数计数）；
- **中栏**：候选判定记录（最近 30 次）——结果标签 + **来源染色 chips**（心情/日程/记忆/未完话题/见闻/梦 各一色，亮/暗主题配色）；
- **右栏**：目标用户卡（上次主动/最近回应/今日已发）+ 主动设置（模型/间隔/每日上限/目标用户）；
- 顶部总览条：「立即尝试一次」+「**试发预览（不发送）**」——预览卡片显示"✅ 当前意愿 / ⚠️ 不会发 + 原因"、各路素材 chips、预览文案。

## 验证

- compileall、verify_057 85、verify_046_nav 31 全绿。