# alpha-0.34（2026-08-16）

## 变更

- **主链 LLM 请求拦截（on_llm_request）**：
  - 拦截从「消息入口 should_call_llm」搬到「on_llm_request（priority 10000）」——在主链
    组装好请求、即将调用 LLM 前拦截，`stop_event` 阻止主链调用 LLM（减少 token）。
  - 拦截不阻断消息传播：记忆插件等在消息入口仍照常捕获；插件直达 LLM 的调用不受影响。
  - 命令消息放行（不拦截），保留可交互性。
  - 拦截默认开启（`intercept.enabled` 默认 true）；拦截成功打印日志。
  - 预留「放行 + 拟人化改写」分支：将来改 `req` 后放行即可让 LLM 收到调整好的请求。
- **记忆注入托管（联动「为你篆刻的历史」）**：
  - 联动时，记忆插件不再自动注入，改由本插件在放行/拟人化模式下通过桥接接口
    `inject_for_event` 注入（`memory.managed_injection` 默认 true）。
  - 拦截模式下不注入（主链不调 LLM，无需注入）。
- 页面资源版本参数升至 `?v=0.34`。

## 说明

- 本版为 0.34 重做后的核心形态，聚焦「主链请求拦截 + 记忆注入托管」；主动对话等旧
  0.34 内容不再沿用。
- 依赖记忆插件 alpha-0.73+ 提供的托管注入桥接接口（`set_injection_managed` /
  `inject_for_event`）。
- 版本备份：工作区 backup 目录下的 `astrbot_plugin_storyteller_alpha-0.34`。
