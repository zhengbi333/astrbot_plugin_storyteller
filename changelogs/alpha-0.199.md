# alpha-0.199

## 能力工具化 · 阶段 2：接管链路「真 tool loop」（原生 function calling）

阶段 1 用文本协议让模型能主动做事（`[DO:能力]{json}`）；本版把接管链路升级为**真正的原生工具调用**，文本协议保留为降级路径。

### 新增：直连带工具通道（`models.chat_with_tools`）

- 复用既有直连信息提取（base_url/api_key/model），请求带 `tools` + `tool_choice: "auto"` + 关闭思考。
- **流式 `tool_calls` 分片聚合**：OpenAI 兼容流里首片带 `id`/`function.name`，后续片只有 `function.arguments` 增量 → 抽出纯函数 `merge_tool_call_delta(calls, tc)` 按 `index` 累积、拼接 arguments（可单测，避免再犯 0.176 那类"聚合丢片段"的错）。
- 文本聚合复用既有「快照去重 + 思考风暴/超长早停」规则（`_accumulate_text`）。
- **不支持自动降级**：400/422 → 抛 `_ToolsUnsupported`；缺 httpx/提取不到直连信息 → `_DirectUnavailable`。

### 新增：接管链路的工具循环（`main._generate_tool_loop` / `_generate_once`）

- `_generate_once` 是生成的统一入口：**原生工具优先** → 不支持/异常 → **降级为文本协议/普通生成**（只记日志，不影响回复）。
- `_generate_tool_loop`：请求带工具 → 有 `tool_calls` 就**执行**（统一走 `capabilities.dispatch`：限额/去重/失败如实告知都在那里）→ 以 `assistant(tool_calls)` + `role=tool` 结果**回填** → 再请求，最多 `capabilities.max_rounds+1` 轮（一轮最多执行 3 个调用；总超时 150 秒）。
- 工具名统一 `story_<能力名>`，与主链注册的 `@filter.llm_tool` 同名（两条链路模型看到的能力一致），执行时用 `cap_name_from_tool` 映射回能力。
- 工具 schema 由能力注册表生成（`build_tool_schemas`）：参数按名/说明推断类型（`items`→数组、`selfie`→布尔、`top_k/limit`→整数），枚举型参数带 `enum`（`memory_write.type`、`schedule_edit.action`、`mood_note.direction`、`share_inner.kind`）。
- 新配置 `capabilities.native_tools`（默认开）——关闭则只用文本协议。

## 验证

- **第十一批专项 25/25**：分片聚合（两调用分槽 / id·name / arguments 分片拼接可解析 / 第二槽独立）；工具 schema（11 个 / `story_` 前缀 / 枚举 / required / items 数组 / 名字映射）；**工具循环**（两轮请求、真执行能力、回填 `role=tool` 与 `assistant.tool_calls`、最终返回文本、去重登记）；**降级**（提供方拒绝 tools → 普通生成兜底）；接管链路整体走原生工具并发出干净文本；静态 5 项。
- **第十二批（真链工具）5/5**：真实 DeepSeek 接受 tools → 返回 `story_memory_write` 调用（参数含 content）→ 回填工具结果再请求 → 得到自然最终回复「好，已经记下来了——明天上午去医院复查，我会提醒你。」且**不再重复调工具**。
- **回归**：第一/二/五/六/七/八/九/十批 169/169；真链全真 11/11；真库 11/11。
- **合计 221/221**。测试脚本：`_st_test/test_iter11.py`、`_st_test/test_full_tools.py`（新增）。

## 下一步（同一目标内）

**阶段 3**：收敛预检测为兜底（仅本轮无工具调用且规则命中时执行），消除"工具 + 正则"双重执行；**面板「能力清单」页**（开关/限额/最近调用记录）；阶段 4 余项打磨（节制与观测）。
