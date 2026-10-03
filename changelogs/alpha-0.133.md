# alpha-0.133

## 清障页模块级 LLM 检查 + 嵌入/重排下拉分类 + 修复探测超时 bug

- **修复「LLM 通道」探测报错**（你报的第 2 点）：`httpx.Timeout(connect=6, read=12)` 构造参数
  不完整（httpx 要求默认值或四个参数全给）→ 已补全（connect/read/write/pool）。
- **每模块自带 LLM 可达性**（你要的第 3 点）：「LLM 通道」单一检查项拆分为 **14 个模块级
  「模块名 · LLM」**（状态/日程/内心/主动/关系/防抖/拦＆改/润色/表情包/发送/记忆/风格/人格/穿搭）：
  每个模块探测自己配置的全部功能模型（内心含梦境/思考/日记/搜索四键，记忆含画像/约定两键），
  逐键列出「功能键：模型名 可用 / 连接失败…」，任一故障该模块即红色点名；
  同一模型接口只探测一次（结果缓存复用）；模块未配专属模型时明确提示「走留空回退策略」。
  原「LLM 通道」项**降级为「回退模型 · LLM」**：探测 models.fallback_provider_id；
  回退未配置且存在未配专属模型的功能时，会点名列出会因此被驳回的功能。
  清障页现共 **32 项**。
- **嵌入 / 重排下拉与 LLM 分类分开**（你确认的第 1 点方案）：
  - `models/providers` 接口支持 `?kind=chat|embedding|rerank`，分别读 AstrBot 的
    get_all_providers / get_all_embedding_providers / get_all_rerank_providers；
  - 前端初始化并行加载 LLM 与嵌入两份列表；`renderSettingField` 按字段自动选择——
    嵌入类字段（memory.embedding_provider_id）用嵌入列表，聊天类字段仍用 LLM 列表，
    下拉上方注明「列表来源：AstrBot『嵌入』模型分类」；
  - 事实说明（答复你）：AstrBot 的嵌入 provider 必须实现 get_embedding 接口、重排 provider
    必须实现 rerank 接口，普通 LLM provider 一般没有——所以用 LLM 列表选嵌入/重排大概率会
    运行失败；现在按分类取各自列表（deepmemory 侧此前已按分类实现，无需改动）。
- 回归：smoke_troubleshoot 25 项（+1：模块级重构后场景覆盖）；verify_057 140 项；
  前端 embedding 下拉分类断言随记忆页渲染覆盖。