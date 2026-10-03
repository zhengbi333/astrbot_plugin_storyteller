# alpha-0.191

## 互动部分补全：对话中说「记住/约定」→ 真实写入长期记忆（+ 上下文条数放宽 0–36 + 全量测试）

### 排查结论（用户关切：互动部分不完善）

用户问「对 Bot 说『你记住 xxx/记忆一下 xxx』，它能不能真的写入长期记忆/未完成的事/约定？其他的呢？」——排查结果：

1. **「记住 xxx」检测不到**：`memory.py` 的 `COMMITMENT_HINTS` 只有「记得/别忘了/一定要/约定/说好/答应/以后/下次/改天/回头/有空/想要/想一起/一起去」——**没有「记住/记一下/记忆一下/帮我记」**。用户说「你记住，我明天去医院」检测不中 → 不提炼 → 不写入；Bot 回复纯话术。
2. **「约定/说好/答应/以后想一起」能写**：命中后 LLM 提炼 → `write_memory(memory_type="promise")`（memory.commitment_enabled 开关控制）。「未完成的事」无专门待办表，但 promise（约定）承载后由 inspiration「约定后续」+ proactive「{未完成}」取材——**前提是 promise 真的被写入**（① 的缺口直接把这条链也掐断）。
3. **工具调用层面**：插件注册的 llm_tools（get_schedule/set_schedule/get_outfit/set_outfit/add_future_plan）与记忆插件的 `deepmem_recall`/`deepmem_remember` 只在 **AstrBot 主链 agent 请求（带 func_tool）** 下执行；「接管改换」是插件直连流式生成（不经主链工具执行器）——**模型在接管改换下无法调用任何工具**，「记住啦」不落库。参考联动（AstrBot 主程序搜索工具「失败可见 + 工具化」、参考插件「记住工具：落库成功才报成功」）→ 本版把这些意图落成本插件的**预检测直连执行**（规则+LLM 提炼 → 桥接写入），与生图/搜索意图同一架构，不改流式链路。
4. **写入后无确认**：`_write_commitment` 后台异步（LLM 提炼 1–3s），模板组装时可能未完成，模型不知道「刚写入」→ 无法自然确认。

### 修复（0.191）

- **意图词扩充**：`COMMITMENT_HINTS` 增加「记住/记一下/记下来/记着/帮我记/记忆一下/存一下/存下来/记录下来」；`detect_commitment` 不变（词表驱动）。
- **提炼 prompt 升级**：`build_commitment_prompt` 输出 JSON `{"content", "memory_type"}`（promise/preference/fact/note）；`json_util` 宽松解析；解析失败回退全文 + `classify_remember` 轻量三档分类（强约定词→promise；偏好词→preference；弱约定词→promise；其余→fact——「别忘了我爱吃辣」正确归 preference）。
- **写入确认 + 幂等**：`_write_commitment` 成功后写 `_memory_written_cache`（会话粒度 10 分钟，含原文 key）；`{记忆}` 锚（两处：接管改换/接管走主链）在 compose 后附一次性确认（「刚才对方要你一直记住的事，你已经写进长期记忆了…」，模型自然确认且不复述成背诵）；同会话同原文 10 分钟只写一次（`on_llm_request` 同步兜底 + `_observe_message` 后台双触发防双写；**修复了幂等 key 用提炼内容比对原文的 bug**）。
- **时序**：`on_llm_request` 接管分支在模板组装前 **await** 记忆写入（有意图且未写过时），保证确认注入可靠。

### 配置

- `intercept.context_count` 范围 **2–12 → 0–36**：0 = 完全不携带上下文（只留当前说话）；`_recent_timeline_text` limit<=0 直接返回空；会话搜索「补主题」回看条数同步跟随（0 则不补）。

### 全量测试（真实对话情景模拟，AstrBot 环境 + 临时数据目录隔离）

- **第一批（流水线 22/22）**：占位符链（18 个全在）；命令消息排除；「记住」写入桥+fact+幂等+确认一次性消费；「约定」→promise；搜索触发/查询词/结果入缓存/隔夜补主题/排除词不搜；上下文 limit 生效与 limit=0；生图硬信号（上文晚霞→context 命中）；弱信号（好看吗→{生图意愿}）；模板无残留；防抖收集→判定→结算→放行；拍平。
- **第二批（模块 24/24）**：时间线正序+说话人标注+当前消息去重；0.188 畸形 JSON（`"07:30,`）修复；状态读写；正负情绪检测；关系接触/阶段；日程 JSON 解析；生图意图命中/非画面不命中；schema 模块≥20 且默认值类型合法；版本三处一致；接管模式解析；灵感引擎/条目；三句剧本消息观察；接管改换全链；bridge 缺失时上下文为空且调用不崩。
- **合计 68/68 全真通过**：第一批流水线 22/22 + 第二批模块 24/24 + 第三批全真模拟 11/11（真实 DeepSeek API + 真实 Tavily + 插件真链）+ **第四批真库全真 11/11（用户授权：测试机不怕污染）**——
  - B1：`记住[测试验证]你记住，我明天上午要去医院复查` → 真实提炼 → **真实 deepmemory 库（deepmemory.db）写入** → 读回验证（content/类型/source_plugin=astrbot_plugin_storyteller）→ 清理后消失；
  - B2：约定 → promise 真库读写；B3：compose_injection 真检索（embedding 真调 SiliconFlow）非空；B4：真时间线读（5 事件）；B6：会话最近记忆接口；B5：结尾 SQL 清理全部 `[测试验证]` 残留（真库无污染，AstrBot 运行中进程不受影响）。
  - F1/F2 真实提炼：`你记住，我明天上午要去医院复查` → `type=fact 对方明天上午要去医院复查`；`我们约定周六下午一起去看电影` → `type=promise 双方约定周六下午一起去看电影`；
  - F3 真实 Tavily「5090 显卡价格」返回 3 结果 + 真 LLM 归纳非空；
  - F4 接管改换全链（真 LLM 生成 87 字）——**模型自然带出约定**（「周六下午的电影可别忘了，我这儿票都订好了」），证明 `{记忆}` 确认注入生效；
  - F5 防抖智能判定真解析；F6 润色非空；F7 配置 utf-8-sig 读写回环；F8 确认注入接口无异常。
- **测试基建留存**：`_st_test\test_pipeline.py`、`test_modules.py`、`test_full_sim.py`、`test_real_db.py`（AstrBot python + `-X utf8` 直接跑；真实 key 从 `cmd_config.json` 读取，不在日志输出；真库用例带 `[测试验证]` 标记并自动清理）。

### 未覆盖（如实说明）

- 真实 LLM 对 0.191 新 prompt 的输出（JSON 稳定性）→ 实机验证；若 DeepSeek 偶发输出散文，parse 兜底为「全文+分类」仍能落库。
- 群聊/telethon；「接管走主链」下 deepmem_remember 等工具调用（主链 agent 行为，属于记忆插件/主链范畴）；Tavily 真实检索（0.189 已验证 HTTP 200 + answer 字段）。
