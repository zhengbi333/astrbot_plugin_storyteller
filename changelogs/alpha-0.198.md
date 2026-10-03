# alpha-0.198

## 能力工具化 · 阶段 1（下）：11 个能力全覆盖 + 主链原生工具注册

承 0.197（能力注册表 + 接管文本协议 + 首批 4 个能力），本版补齐**全部计划能力**，并让**主链模式**也能原生调用。

### 七个新能力（与首批共用同一套实现）

| 能力 | 作用 | 关键约束 |
|---|---|---|
| `photo_take` | 画一张图（或角色自拍）**并直接发出去** | 生成前查配额；失败/未配置 → `next_hint` 要求如实说"没拍成"，**禁止说"我发给你了"**；成功后提示"别复述画面、别说我发给你" |
| `schedule_edit` | 改当天某时段安排 / 记未来规划（`action=replace|future`） | 原安排自动进延误池；提示"别把整张日程念出来" |
| `outfit_change` | 换当前穿搭（从衣柜选）/ 往衣柜添一件 | 提示"别逐件念" |
| `proactive_schedule` | **记下答应对方的事**（承诺回访） | 写 `promise` 记忆（importance 0.75）+ 有时间则同时记未来规划 → 由**既有「约定后续」由头链路**自然兑现；写不进去时明确要求"别在回复里承诺" |
| `mood_note` | **情绪随对话起伏**（自述式，±0.05 且带涟漪） | 幅度受上限约束；提示"别解释机制" |
| `share_inner` | 分享**梦 / 见闻 / 日记** | 同一内容 **6 小时冷却**（不反复念叨）；没有内容时如实说"最近没做梦/没刷到"，不许编 |
| `history_lookup` | **翻最近的聊天记录**（不是长期记忆，是原话） | 无记录 → 如实说记不清 |

→ 至此阶段 4 的"像人"清单里（承诺回访 / 情绪自述 / 分享内心 / 回忆检索 / 看历史）**已全部以能力形式落地**；阶段 4 后续只做节制打磨与面板观测。

### 主链模式：11 个能力注册为原生工具

- 新增 11 个 `@filter.llm_tool`（`story_*` 前缀，与既有 5 个日程/穿搭工具并存）：`story_memory_write` `story_memory_recall` `story_web_lookup` `story_emoji_send` `story_photo_take` `story_schedule_edit` `story_outfit_change` `story_proactive_schedule` `story_mood_note` `story_share_inner` `story_history_lookup`。
- 全部薄转发到同一 `capabilities.dispatch` → **主链（原生 function calling）与接管（文本协议）行为一致，只换传输层**。
- 返回统一 JSON（含 `next_hint`）：工具结果直接引导模型下一句怎么说；失败一律 `ok=false` + 如实告知要求。
- 启动日志实证：**16 个 LLM 工具注册成功**（5 原有 + 11 新能力）。

### 配置（`capabilities` 模块）

新增各能力的每日限额：`schedule_edit_daily` / `outfit_change_daily` / `proactive_schedule_daily` / `mood_note_daily`（默认 8）/ `share_inner_daily` / `history_lookup_daily`（0=不限）；`photo_take` 复用 `image.max_daily`。

## 验证

- **第十批专项 20/20**：11 个能力齐备（声明 + 注册表）；日程 replace/future 真实落库；穿搭换装/添衣；情绪 tone 真实上升；见闻分享成功 + **同条冷却** + 无内容如实空态；历史接口；**承诺写入 promise 且同时记未来规划**；生图成功且真发送 + `next_hint` 禁止复述；**失败时不谎称**（桥缺失 → ok=false + 如实说）；静态（11 个 `story_*` 工具、限额键齐备）。
- **回归**：第一批 22/22、第二批 24/24、第五批 22/22、第六批 30/30、第七批 17/17、第八批 10/10、第九批 24/24。
- **真链**：全真模拟 11/11 + 真库 11/11。
- **合计 191/191**。测试脚本：`_st_test/test_iter10.py`（新增）。

## 下一步（同一目标内）

① 面板「能力清单」页（哪些能力开、限额、最近调用记录）；② **阶段 2**：接管链路真 tool loop（`chat_text` 传 tools + 流式 `tool_calls` 分片聚合 + 多轮/熔断/降级）；③ **阶段 3**：收敛预检测为兜底（消除与工具的双重执行）；④ 阶段 4 余项：节制与观测打磨。
