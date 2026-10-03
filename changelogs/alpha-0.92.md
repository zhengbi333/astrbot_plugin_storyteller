# alpha-0.92 —— 流式重试次数可配（models.stream_retry）+ 超时归属澄清

> 用户重启后日志面板的报错经核实：**全部来自第三方插件 private_companion 的 daily_review**
> （provider=siliconflow/deepseek-ai/DeepSeek-V4-Pro）。根因相同（推理模型 Pro × 非流式 ×
> 120s 客户端超时），但**不是本插件**——本插件 storyteller.log 在 alpha-0.91 后无任何
> "日程自动生成失败"记录（我们的 schedule 已配官方 vision Flash、回退=Flash，都是非推理快模型）。
> AstrBot 日志另两条：① `default_provider_id is empty → 用 Pro 兜底`（用户未在 WebUI 设默认模型，
> 属环境配置，建议在 WebUI「配置」页设默认对话模型为 Flash，本插件不改 AstrBot）；
> ② `models.dev 连接失败` 是 AstrBot 拉模型元数据（WebUI 展示用），不影响生成，可忽略。

## 变更

- **`models.stream_retry`（默认 2）**：流式调用遇到超时/失败自动重试次数，可在
  「设置 → 模型配置」调整（默认 2 = 初次 + 2 次重试，共最多 3 次尝试）；
  网络差或上游偶发慢时调高，插件的「一键生成」更抗超时。
- `chat_text` 循环语义修正：`retry_count` 表示"重试次数"（非总尝试数）。

## 测试

- `smoke_story_chattext.py`：流式聚合 / 首败重试成功 / 全失败(3 次)回退非流式 /
  关流式走非流式 / 双失败抛异常 全过
- `smoke_story_takeover.py` 95 / `smoke_story_autoplan.py` / `verify_057` 84 无回归
