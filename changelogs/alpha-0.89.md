# alpha-0.89 —— 直连超时排查 + 流式开关 + 穿搭 LLM 直连（一键生成/像人可改）

> ① 排查"生成日程报 [OpenAI] Request timed out"：确认非插件逻辑 bug——
>   AstrBot 连通性测试只是 `models.list()`（列模型，1 秒）；真正生成走非流式
>   `chat.completions.create`，**SiliconFlow DeepSeek 系对非流式长输出（整份日程 JSON）响应慢，
>   超过 SDK 超时（默认 120s）** → APITimeoutError 重试 5 次（request_max_retries=5）→
>   "Request timed out"。provider_stats 里同模型全部 1~19s 完成，无 >100s——是该请求临时慢，
>   非配置错误。**其它模块同样有风险**（16 处直连共享非流式路径）。
> ② 按用户拍板：**不全面强制流式**，改为「设置 → 模型配置」加**流式开关**（默认开），
>   直连生成优先流式（更稳、规避超时），关闭则完全回到旧行为。
> ③ 穿搭模块补全：直连 LLM（provider_id）+「一键生成穿搭」「一键生成衣柜」+ 像人一样可改。

## 变更

1. **`models.chat_text` 统一直连封装**（带 `models.stream_enabled` 开关，默认开）：
   - 开关开：优先 `text_chat_stream`（逐 chunk 聚合，末尾 usage 保留），失败自动回退非流式；
   - 开关关：直接非流式 `text_chat`（与旧行为一致）；
   - 返回对象兼容 `completion_text` / `usage`，`_record_usage` 与解析代码零改动；
   - 除接管改换（保留自身 90s 超时 + system_prompt 兼容 + 空内容判失败）外，
     judge/日程/状态/人格/风格/润色/梦境/思考/画像/约定/防抖判定/主动/穿搭 全部经此封装；
   - 失败语义：直接抛异常（各调用点已有外层捕获，接管可正确判 blocked）。
2. **穿搭模块**：
   - `wardrobe.provider_id`（穿搭生成模型，下拉）；`FUNCTION_KEYS.wardrobe_gen`；
   - `wardrobe.py`：`build_wardrobe_generate_prompt`（mode=outfit 从衣柜选 2~5 件 /
     mode=closet 生成 10~25 件）+ `parse_wardrobe`；
   - page_api：`wardrobe/generate`（一键生成穿搭）、`wardrobe/generate_closet`（一键生成衣柜）；
   - 前端穿搭页：中栏「一键生成穿搭」、左栏「一键生成衣柜」、右栏生成模型下拉；
   - **像人可改**：对话"我给你买了新衣服 xxx" → `closet` 检测 → 决策 `add_closet`（加进衣柜）；
     "你穿上 xxx" → `dress`（改穿搭）已有；决策 prompt 现含衣柜上下文。

## 测试

- `smoke_story_autoplan.py` 31 项（+closet 检测、add_closet 落库、wardrobe prompt/parse）
- `smoke_story_takeover.py` 95 / `verify_057_pages.js` 83（穿搭页生成按钮/模型下拉断言）
- smart 28 / ui_state 14 / intercept 3 / log 10 / verify_045 / propagate / scan 0 / nav 31
