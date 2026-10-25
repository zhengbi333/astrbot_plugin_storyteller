# alpha-0.241

## 外部工具桥：接管链路也能用上 AstrBot / MCP / 其它插件的工具

### 问题

「接管改换」模式由本插件自己拼 `tools`，只包含自己的 11 个能力；AstrBot 主链上那些工具
（MCP 服务器、其它插件注册的 `@filter.llm_tool`，例如「为你而在的认知」的读写文件与抓网页）
**在接管模式下完全看不到**。于是同一个 Bot，换模式就换了一套手。

### 做法（不复制工具，只接线）

1. `capabilities.astrbot_tools_enabled`（**默认关**）：开启后，把 AstrBot **已激活**工具的描述
   （`get_func_desc_openai_style()`）并入本轮的 `tools`。
2. `capabilities.astrbot_tools_allowlist`：逗号分隔的工具名白名单，留空表示全部；建议只放要用的几个。
3. 模型调到时用 `ext:<name>` 前缀分流，执行交给 AstrBot 的 `get_full_tool_set()` →
   `tool.call(...)` —— 这条路径**天然经过面板里的「谁能用」权限校验**（`_PermissionGuardedTool`），
   不是绕过，而是复用。
4. 上下文用代理对象 `_ToolCallContext`：`.context.event` 供 AstrBot 判权限与调 handler，
   其余属性透传给插件自己的 `Context`。
5. 外部工具的失败（参数不对 / 内部异常 / 没有这个工具 / 开关没开）都转成**明确文案**回填给模型，
   避免它把"没做成"说成"做成了"。

### 为什么默认关闭

开了之后，**任何能跟 Bot 说话的人**都能触发这些工具（AstrBot 的权限层能挡 admin 级工具，
但默认权限是 member 即放行）。所以默认关、由使用者显式打开并配白名单。

## 验证

`_st_test/audit_59_external_tools_bridge.py` —— **20/20**：

| 组 | 覆盖 |
|---|---|
| A | 默认关闭：不给描述、名字集合为空、直接调用被拒 |
| B | 打开后给出全部已激活工具；白名单只放行点名的 |
| C | 执行成功带结果；参数原样传递；**代理上下文带 event**；参数错/内部异常/缺工具 都有明确状态 |
| D | 接线静态检查（`ext:` 常量、tools 并入、分发识别、执行分支、走 `tool.call`） |
| E | schema 两个新键存在且默认值正确 |

另跑：既有 26 批本地回归 + 相关探针（`audit_01/20/44/51/57/58`）。
