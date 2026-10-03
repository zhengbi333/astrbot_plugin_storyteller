# alpha-0.91 —— 超时问题（纯插件侧解决）：流式 + 超时自动重试；转盘长文本显示全

> 修正方向：**不修改 AstrBot 架构/配置**（发布时用户不可能去改 AstrBot，升级也会覆盖），
> 超时解决方案完全放在插件内部，任何人的 AstrBot 环境开箱即用：
> `models.chat_text` 统一封装 = **流式优先 + 超时自动重试 1 次 + 回退非流式**。

## 变更

1. **超时解决（插件自足）**：
   - `chat_text` 默认流式（`models.stream_enabled` 开）——AstrBot 的 OpenAI 兼容 provider
     非流式长输出在 SiliconFlow/DeepSeek V4 系会超过客户端 120s 超时（APITimeoutError，
     换官方 API 也一样，因为根因是"推理模型先思考再生成 × 非流式一次性等到底"）；
   - **流式超时/失败自动重试 1 次**（超时多为偶发，重试通常命中）；两次全失败回退非流式；
     非流式也失败才抛异常（调用方已有捕获，接管可正确判 blocked）；
   - `stream_enabled=false` 时完全回到旧非流式行为。
   - **任何用户无需改 AstrBot 配置**：无论 AstrBot provider 的 timeout 是多少，
     本插件先用"流式 + 重试"兜底。
2. **转盘长文本显示全**：`.sched-act`/`.sched-line .hint` 去掉 nowrap/ellipsis，
   改 `white-space: normal; word-break: break-word`——长活动（如"熬夜到四点多…"）折叠态完整显示。

## 测试

- 新增 `smoke_story_chattext.py`：流式聚合/首败重试成功/全败回退非流式/关流式走非流式/双失败抛异常
- 全量：takeover 95 / smart 28 / ui_state 14 / intercept 3 / log 10 / autoplan / verify_045 /
  propagate / scan 0 / verify_057 84 / nav 31 全绿
- 视觉自检：转盘长活动文本完整显示截图核对
