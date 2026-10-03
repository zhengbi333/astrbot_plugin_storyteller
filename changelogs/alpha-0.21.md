# alpha-0.21（2026-08-08）

## 变更

- **「插件调试」选项卡改为子选项卡结构**：
  - 「诊断」：原前端诊断 + 运行时日志；
  - 「拦截与改换」（新）：LLM 请求拦截 / 用户当前请求 两个区块。
- **LLM 请求拦截**（`intercept` 功能大类，设置页独立模块 + 总开关）：
  - 拦截 AstrBot 发送给 LLM 的**对话/理解请求**（主链对话、图片/文档理解等走 `on_llm_request` 钩子的请求），
    记录将发送的 prompt / 系统提示 / 上下文摘要 / 图片数；
  - 「用户当前请求」同步记录拦截时获取的用户消息文本；
  - `intercept.block_llm` 开启时调用 `event.stop_event()` **阻断发送**（机器人不回复），关闭则只记录不阻断；
  - **不拦截**记忆总结等插件自行调用模型的内容（它们不经 `on_llm_request` 钩子），保证插件兼容性；
  - 记录为内存环形缓冲（上限可配，默认 50，超限丢最早），可一键清空。
- 新增接口：`GET /intercept/status`、`GET /intercept/requests`、`GET /intercept/user_requests`、`POST /intercept/clear`。
- 页面资源版本参数升至 `?v=0.21`。

## 说明

- 拦截为调试/研究用途：默认关闭（`intercept.enabled=false`）；开启后记得按需关闭 `block_llm` 或总开关。
- 专项验证：环形缓冲上限与顺序、用户请求记录、清空、拦截记录+阻断（stop_event）、总开关关闭不干预。
- 版本备份：工作区 backup 目录下的 `astrbot_plugin_storyteller_alpha-0.21`。
