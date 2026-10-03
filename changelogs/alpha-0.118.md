# alpha-0.118

## 主动消息「未回应动态机制」（你定夺：全套 + 心情联动）

借鉴示例插件 private_companion 的 friend_unanswered 阶梯思路（实现非雷同）。每用户维护连续未回应计数，落盘 `plugin_data/.../proactive_user_state.json`（重启延续「还悬着」的记忆）：

- **间隔放大**：连续未回应超过 `unanswered_slowdown_start`（默认 2 次）后，下次主动间隔 = 基础间隔 × `min(unanswered_max_interval_multiplier 默认 2.2, 1.0 + 超出数×0.35)`——被晾着就不频繁往上凑。
- **阶梯降级文案**（内置模板自动附加，不新增占位符）：
  - 未回应 1 次：「对方还没接话——放轻一点，别催别追问；把话说软一些」；
  - 2 次：「对方有一阵没回应了——低压，别连问；没什么要紧的就 :NO:」；
  - ≥3 次：「连着几条都是你发、对方没回——退一步，留空间；除非由头真的非说不可，否则 :NO:」；
  - :NO: 规则新增「对方连续没回应明显不想聊」。
- **静默闸门**：连续未回应 ≥ `silent_after_streak`（3）且距首次悬置 ≥ `silent_after_hours`（24）→ 暂停普通主动（**检查顺序在每日上限之前**），对方先开口即全部归位。
- **温度标签**：基础 0.54 − 未回应扣分（每次 −0.08 封顶 −0.32）+ 刚回应加成（6h +0.12 / 24h +0.06）− 悬置超 4h 扣分 − 心情偏收扣分 → 温热 / 普通 / 偏冷；目标用户卡展示（连续未回应 N 次 · 温度 · 已静默）。
- **心情联动（写进 presence 并反馈）**：
  - 连续未回应达 `mood_down_streak`（默认 2）触发一次「冷落」染色（tone −0.06 / tempo −0.04）/（涟漪「对方一直没回」），同一轮不重复降；
  - 对方回复 → streak 归位 + 「回应」染色回升（tone +0.06）；
  - 心情偏收（mood 低落/tone<−0.3）时温度 −0.08 → 主动意愿也变淡；
  - `mood_link` 总开关；受 `presence.light_evolve_enabled` 约束。

## 修复「昨天说好了」幻觉由头（问题 1 根因）

- 约定后续/记忆由头原实现把 `_recent_memory_hint`（全量最近记忆）硬包成「之前说好/约好的事」，库里只要有任何偏好/身份记忆就会让模型演绎出「昨天说好的，今天你那边怎么样了」。
- 改为 `_recent_promise_hint`：只取 deepmemory `memory_type="promise"` 的记忆；无约定则这两个由头直接不出。与测试人格无关（主动生成不注入人格）。

## 设置项（全部可调）

`unanswered_slowdown_start`(2) / `unanswered_max_interval_multiplier`(2.2) / `silent_after_streak`(3) / `silent_after_hours`(24) / `mood_link`(开) / `mood_down_streak`(2)。

## 测试

- 新 `smoke_proactive_dynamic.py` 27 项（streak 推进/间隔放大/闸门优先于上限/温度/阶梯文案/心情联动/持久化）。
- verify_057 主动页 +3 断言（动态设置项、用户卡未回应/温度/静默）。