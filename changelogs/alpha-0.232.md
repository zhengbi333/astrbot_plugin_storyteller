# alpha-0.232

## 25 模块深度自检 · 第 23 轮：settings 设置 —— 4 个「声明了却不生效」的配置

### 方法
三方键集合摊平对比：`_conf_schema.json`（**187 键**）↔ 前端表单（**72 键**）↔ 代码实际读取（**136 键**）。

### 好消息
- 代码读取的 136 键**全部**在 schema 里；前端 72 键**全部**在 schema 里 ✅
- 保存接口用 **schema 做键过滤** + 按 schema 类型强制转换 ✅（不盲写任意键）
- 类型容错：`"true"` / `"0.3"` 正确解释；缺键用默认值 ✅

### 🔴 查出 4 个开关"配置了不生效"
| 配置项 | 承诺 | 实际 |
|---|---|---|
| `general.enabled` | 关闭后插件不再参与对话 | **全仓无读取 → 关了没用** |
| `rewrite.rewrite_user_enabled` | 放行时润色用户消息（默认**关**） | 从未读取；该处读的是 `rewrite.enabled`（默认**开**）→ **默认就会多调一次模型改写用户的话** |
| `debounce.recall_filter` | 窗口内撤回则移除该消息（默认开） | 撤回处理无条件执行，开关没接 |
| `voice.verbosity` | 话量倾向 | 未使用（实际生效的是风格档案里的 `verbosity` 字段） |

### 修复
1. `on_llm_request` + `on_llm_response` 都加 `general.enabled` 检查 → 总开关真正生效（面板仍可用）
2. "润色用户消息"改读 `rewrite.rewrite_user_enabled`（默认关）→ 默认不再多调模型改用户的话
3. `debounce.handle` 撤回分支接入 `debounce.recall_filter`
4. `voice.verbosity` 的 hint 如实标注"当前由风格档案接管，此项暂不生效"

### 验证 11/11
三方一致性（① ② ③）、保存接口键过滤、类型强制、**四个开关的读取断言**。
动态拼键（表驱动读取）已逐个核实：`capabilities.*_daily` / `image.api_*` / `*.provider_id` / `proactive.*`。
**回归 498/498。**

### 我自己的 3 次纠错
① schema 展平在顶层找 `items`（实际在模块层）→ 三个断言全是假失败；② 键正则漏 `_config().float("x")` 写法 → 误报 87 个"未使用"；
③ 正则放宽后把 provider 字段当插件键 → 误报"未声明"。
**教训：审计脚本本身也是被测对象，断言失败先确认扫描口径。**
