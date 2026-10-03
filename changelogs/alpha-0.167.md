# alpha-0.167

## 里程碑修复：直连通道丢弃 system_prompt——模型从未收到人设注入（"没看到设定"真正根因）

- **用户洞察（完全正确）**："是不是发送给 LLM 还要经过一道我们不知道的工序？我不大相信这是模型行为，因为这个模型很先进。"——**逐步核查 AstrBot provider 链后，真凶是我插件自己的直连通道**：
  - `models.chat_text` **直连优先**（models.direct_enabled=True）：从 provider 提取 base_url/api_key/model 自建 httpx 请求（快、可控超时、可关思考）；
  - **直连组装 body 时只放了 `messages=[{"role":"user","content": prompt}]` —— `system_prompt`（1500 字人设+全部锚）被完全丢弃！**
  - 于是模型实际只收到引导句 user prompt（0.161 前是"请以以上设定的身份、本次对话上下文，自然回应对方刚刚说的话。"——**难怪它索要"设定/上下文"**；0.161 后是"直接回应对方刚刚说的话…"——它变成"走神/让我回应哪句话"），**"你是阡墨/风格/状态/日程/标签"从未到达模型**；
  - **为什么之前看起来"注入完整"**：`_record_sent` 快照记录的是"插件**打算**发送的内容"，页面快照/审计脚本（组装侧）全部正常——**组装正确 ≠ 实际发送**；润色之所以"看得到"阡墨（17:00 日志），因为润色把全部内容拼进了 **prompt**（单通道）。
- **修复**：
  1. **直连（流式+非流式）显式携带 system_prompt**：`messages=[{"role":"system","content":…},{"role":"user","content":…}]`（新增 `_direct_messages`）；`chat_text` 从 kwargs 取出 `direct_system` 并在直连与原通道回退（流式/非流式）都显式传入；
  2. **provider 兼容**：原通道回退时 provider 不接受 `system_prompt` 参数则去掉重试（老接口/测试桩不炸）；
  3. **A 快照落盘**：`_record_sent` 写 `plugin_data/sent_snapshot.json`（滚动 30 条）——以后任何时刻可读"实际打算发送内容"（排障金矿；页面快照依然可用）。
- **B（空段占位"（本轮对话的第一句。）"）不再需要**：根因是 system_prompt 未发送而非空段措辞，已取消。

## 验证
- 41 项冒烟全绿（smoke_story_takeover 139 项，+2：`_direct_messages` 含 system/user、无 system 时仅 user）
- 交互级/layout/deepmemory 回归全绿（见部署输出）
- **请实机重载后测试**：/reset → 「你好」——预期**首次生成**即正常回应（不再触发索要检测）。
