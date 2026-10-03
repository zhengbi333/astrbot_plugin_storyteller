# alpha-0.150

## 平台差异修复轮（朋友 Linux/Docker 环境实测三个问题）

### ① 日程/衣柜生成「结果无法解析为 JSON」

- 根因方向：不同平台/模型的 LLM 输出格式差异（markdown 围栏、前言后记、尾部逗号、列表 vs 对象等），旧解析器只有「剥花括号」两档，容错不足。
- 修复：新增统一宽松解析 `json_util.parse_json_lenient`（剥 ```json 围栏 → 直接解析 → 提取外花括号 → 修尾部逗号，支持对象与数组），**接入全部 7 处生成解析**：日程（schedule）、衣柜/穿搭（wardrobe）、状态（presence）、风格档案（voice）、画像列表（memory profile）、回复判定（reply_pipeline）、关系判断（main.py）；
- 仍失败时**记录原始输出前 240 字**到日志——再遇到具体格式，贴回来即可精准适配。

### ② 主动消息「发送接口返回失败（适配器未连接/目标不可达？）」

- 根因方向：目标用户 ID 若带平台前缀（如 `qq:123456` / `aiocqhttp:123456`），会拼出无效会话 `aiocqhttp:FriendMessage:qq:123456` → 发送失败。Docker/napcat 环境用户填法不一，触发概率更高。
- 修复：`_resolve_session` 归一化（任何 `前缀:数字` / 纯数字都转成 `{platform}:FriendMessage:{数字}`）；发送失败日志带上完整 session 与异常详情，便于定位。

### ③ 防抖「消息被删只剩第一条 + 最后一句话到回复 34 秒」

- **34 秒根因**：智能判定默认开启后，每条消息触发一次 LLM 判定，判定 continue 又把等待重置 8s——4 条消息连发 = 判定多次 + 8s×N(实测复现组合)。
- 修复：每条消息重置**快速确认窗口**（`smart_max_quiet_wait` 默认 8s→**3s**）；判定仍在后台跑——release 可提前结算，**判定只减时不加时**（慢判定/失败由窗口兜底），连发场景 34s → ≤3s；
- **合并内容完整性**：`_reconstruct` 全面防御——AstrBot 组件导入失败/重构异常时退化为**直接写回 `event.message_str` + `message_obj.message_str`**（此前重构异常被静默吞掉，主链只能看到第一条——正是「只有第一条被注入」的另一候选根因）；
- 新增回归场景：快速连发 4 条消息（含表情文本）→ 放行耗时 <3s、合并文本 4 条完整。

### 验证

- smoke_story_smart **32 项**（+4 连发场景）、smoke_image_intent 22、smoke_debounce2 5、**40 项冒烟 0 失败**、前端 interact 44/057 169/046 31；语法全过。