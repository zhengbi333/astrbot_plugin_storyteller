# alpha-0.134

## 修复 bridge 报错与嵌入下拉空列表 + 时间线紧凑（0.133 验收反馈）

- **修复「Plugin bridge endpoint is invalid.」**（你报的第 2 点，确凿根因）：AstrBot 插件页
  前端桥**禁止 endpoint 字符串内联 `?`**（`endpoint.includes("?")` 直接抛错）。0.133 我把
  `kind=embedding` 写进了 endpoint（`models/providers?kind=embedding`）→ 页面一打开就抛该错误，
  且嵌入列表请求失败被静默兜底 → 下拉为空。已改为桥的契约形式 `apiGet("models/providers", { kind: "embedding" })`。
- **顺带修复表情包上传的同一隐患**：`files:upload` 通道同样走该校验且没有 params 参数——
  此前 `emoji/upload?cid=xx` 上传也会被拒绝。改为**文件名携带分类 id**（`<cid>__<原文件名>`）
  上传无 query 端点，后端从文件名前缀解析（兼容旧 ?cid 形式）。
- **嵌入下拉数据源修正**（你报的第 4 点，正确的观察）：AstrBot 的嵌入/重排是**独立于对话模型的
  另一类配置**（openai_embedding 等，`provider_type=embedding`、字段 embedding_api_key/
  embedding_api_base/embedding_model）。`model_providers` 的嵌入/重排列表改为**多重回退**：
  专用 context 接口（get_all_embedding_providers；重排无此接口）→ `provider_manager.embedding_provider_insts / rerank_provider_insts` → `inst_map` 按 provider_type 过滤——
  你的 `openai_embedding（Qwen3-VL-Embedding-8B）` 现在会出现在记忆页嵌入下拉中；
  选项标签带模型名。
- **deepmemory 重排下拉同修**（你问的第 1 点）：deepmemory 页面此前按分类取列表（嵌入正常）；
  但**重排**降级到 LLM 列表（AstrBot 无 get_all_rerank_providers context 接口）——已改为
  专用接口 → manager.rerank_provider_insts → inst_map 兜底（deepmemory alpha-0.77）。
- **记忆页时间线再紧凑**（你要的第 3 点）：真因是 `.field-row` 默认 `justify-content: space-between`
  把「谁·会话·时间」推到左右两端 → 间隔巨大；已强制 left 对齐 + 徽标/提示字缩小 + 行距收紧 +
  **每页 10 条** + 条目卡限宽 520px（消息卡不再撑满整栏）。
- 回归：smoke_troubleshoot 28 项（+3 下拉分类）；verify_057 141 项（+1 嵌入下拉断言，时间线断言改 10 条）。