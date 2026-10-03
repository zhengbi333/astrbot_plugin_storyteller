# alpha-0.143

## 全面检查轮：交互级模拟 + 历史冒烟补跑（用户要求真实功能模拟）

- **新增交互级模拟 `verify_interact.js`（20 项）**：在 DOM 桩上模拟真实用户操作链路——按钮点击 → 桥接 API 调用 → 界面刷新结果：
  - 清障页：初始「未检测」、一键只读测试（点击 → diag/run → 绿/红结果渲染、LLM 项保持未测）、单项测试（点击 → diag/check → 结果渲染）、一键 LLM 测试（点击 → diag/llm_test → 耗时/超时失败项渲染）；
  - Token 页：默认陪伴明细、来源 pill 切换 → 明细数据变化；
  - 发送页：第一页 5 条、队列翻页（下一页按钮 → 第 6/7 条出现、第 1 条消失）；
  - 记忆页：时间线第一页 10 条、翻页（11-20 条）、「检测联动」按钮点击后重渲染。
  - 桩增强：事件监听器快照迭代防重入、布尔属性（data-pro-test-link）解析、querySelector 支持、带 id 子段同步进 getElementById 缓存（pager 绑定依赖）。
- **6 个从未跑过的历史冒烟修复并全绿**：smoke_proactive / smoke_alpha054 / smoke_test2 / smoke_test3 / smoke_story_appearance / smoke_story_debounce——桩补全（astrbot.api.web / quart / TextPart / ProviderRequest / LLMResponse）+ 断言更新到当前语义（库模式背景命名、防抖放行语义、summary.group_trigger_events、优先级模块已删）。
- **回归收集器 `run_all.py`**：38 项冒烟一键汇总（23 主回归 + 15 补充/历史），utf-8 收集。
- 结果：38/38 全绿（27s）；页面级 verify_057 149 项、导航 verify_046 31 项、交互级 verify_interact 20 项全绿；静态残留/语法/雷同/四向一致性均通过。生产代码零改动。
