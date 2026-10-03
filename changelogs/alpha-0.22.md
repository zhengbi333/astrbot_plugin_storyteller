# alpha-0.22（2026-08-08）

## 变更

- **拦截记录补充多模态 URL**：LLM 请求拦截记录新增图片 URL 列表（最多 5 个，各截断 300 字符）与音频 URL 列表（最多 3 个），前端展示对应区块——完整呈现「将发送给 LLM 的内容」。
- 说明：拦截点即 AstrBot 组装好、即将发给 LLM Provider 的 `ProviderRequest`（prompt/系统提示/上下文/图片/音频），并非协议端（napcat 等）消息；阻断发生在 LLM 调用之前，不产生 token 消耗。
- 页面资源版本参数升至 `?v=0.22`。

## 说明

- 版本备份：工作区 backup 目录下的 `astrbot_plugin_storyteller_alpha-0.22`。
