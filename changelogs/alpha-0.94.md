# alpha-0.94

## 修复「设置页开关不自动保存」（真凶）

- `renderSettingField` 渲染的布尔开关 checkbox **漏标 `data-type="bool"`**：
  - **设置页**（`bindSettingsEvents`）的选择器只认 `[data-type='bool']` → 开关根本没绑定保存监听，点了毫无反应（用户反馈「点击开关不会自动保存」）；
  - **模块页**（`bindSettingsIn`）落入 else 分支按文本处理 → 存的是 `node.value`（checkbox 恒为 `"on"`）而非 `checked` → 开关只能"开"不能"关"。
- 修复：checkbox 补 `data-type="bool"`；两处绑定函数再加兜底——凡 `[data-setting]` 的原生 checkbox 一律按布尔处理（读 `checked`）。
- 受影响面：所有经 `renderSettingField` 渲染的布尔设置项（设置页全部模块 + 各模块页内联设置项）；主开关（masterSwitch，按 id 绑定）此前正常不受影响。

## 修复「生成成功却不落盘 + 卡生成中」（流式全量快照去重）

- **根因（实锤）**：AstrBot 流式接口在增量 chunk 之外，**末尾会再 yield 一个 `completion_text`=整段完整文本的「全量快照」chunk**。旧聚合逻辑把增量与全量直接拼接 → 正文翻倍（两份 JSON 首尾相接）→ `parse_schedule`/`parse_wardrobe` 必失败 → 静默 return → Token 照记、日程/穿搭不落盘、无任何日志。
- 修复（`models.chat_text` 流式聚合）：新 chunk 与已聚合正文互为前缀（忽略首尾空白）时**只保留更长者**，普通增量照常追加。
- 冒烟新增：快照去重（正文不翻倍/usage 保留/JSON 可解析）、等长快照忽略。

## 推理风暴 / 内容跑飞 早停（新增两个设置项）

- `models.stream_max_think_chars`（默认 8000）：思考内容（reasoning_content，不计入正文）累计超限立即放弃本次尝试——DeepSeek V4 系推理模型对简单生成任务可能思考几万 Token/数分钟（token.json 实证：单日日程任务烧掉 5.3 万输出 Token），此上限让其快速失败并给出明确提示，不再空等。
- `models.stream_max_chars`（默认 12000）：正文累计超限立即放弃（防模型跑飞重复输出）。
- 非流式超时改抛带中文指引的 `RuntimeError`（保留上游详情）："生成超时（单次限时 Ns）……可在设置调大或换非推理模型"。

## 生成路由「诚实反馈 + 全程日志」

- `main._generate_schedule` 改为返回结果字典（ok/entries/outfit/error），后台节拍调用方无感；
- `schedule/generate` 路由：失败时如实返回具体原因（此前永远返回成功，前端误报"已生成并保存"）；
- 三个生成路由（日程/穿搭/衣柜）入口记 INFO 日志；解析失败记 WARNING 并附原文前 120 字预览——以后从「调试」页或 storyteller.log 即可直接看到生成卡在哪一步。

## 前端：生成按钮显示已等待秒数

- 「一键生成日程/穿搭/衣柜/风格/人格」五个生成按钮进入忙碌态后每秒累加显示（"生成中… 7s"），让用户明确知道仍在工作而非卡死；沙箱无 setInterval 时静默退化为纯文本（不影响测试桩）。

## 验证

- chat_text 冒烟 18 项（新增快照去重×3 / 思考风暴 / 内容超长 / 非流式超时提示）；takeover 95、smart 28、ui_state 14、intercept 3、log 10、autoplan、verify_045、propagate、雷同扫描 0、verify_046_nav 31、verify_057 84；`python -m compileall` 全绿。
