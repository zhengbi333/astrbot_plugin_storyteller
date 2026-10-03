# alpha-0.132

## 清障页新增两项外部依赖自检（你问的「LLM 可达性 / 下游客户端」）

- **「LLM 通道」**（`llm_channel`，你确认的零 token 方案）：对每个已配置 provider 提取直连信息
  （base_url/api_key/model），**HTTP GET {base_url}/models** 验证接口可达、API Key 有效（401 识别）、
  模型真实存在（不在列表会点名）；个别网关没有 /models 端点（404/405）时**降级为 TCP 连接检测**；
  不做对话生成、**零 token 消耗**、几秒完成；多个 provider 逐一探测并列出「模型名：可用」。
  无标准接口信息的 provider 明确标注「跳过（由 AstrBot 客户端管理）」。
- **「下游客户端」**（`platforms`，你确认的方案）：枚举 AstrBot 全部消息平台适配器，用**官方状态**
  （Platform.get_stats：status/error_count/last_error）判断——`running` = 绿色「已连接」；
  `pending/error/stopped` = 红色并显示状态与末次错误（NapCat 断连会直接点名）。
- 清障页现在共 **18 项**；通过项的结果块也显示检测详情（如「deepseek-v4：可用」「NapCat 已连接」），
  不再只有「功能正常」四个字。
- 回归：smoke_troubleshoot 24 项（+9：18 项全量/LLM 跳过与四种失败分支/平台 running 与 error/
  网络单跑）；verify_057 140 项（+2：LLM 通道、下游客户端断言）。