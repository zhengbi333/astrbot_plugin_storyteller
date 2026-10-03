# alpha-0.230

## 25 模块深度自检 · 第 19 轮：memory 记忆 —— 两套约定词表不一致，导致「约好」类约定不写记忆

### 执行链
- **写入**：观察层判定（`detect_profile` / `detect_commitment`）→ 缓冲 → LLM 提炼 → `write_memory`（经桥接）；
  接管链路另有承诺同步兜底。
- **托管注入**：`_sync_memory_managed()` 动态同步"记忆插件是否跳过自动注入"（避免双份），
  再由 `_inject_memory()` → `bridge.inject_for_event()` **完全委托**给记忆插件。
- **分类** `classify_remember()`：三类 `promise` / `preference` / `fact`。
- **清洗** `_clean_memory_meta()`：剔除"…这条消息旨在说明…"这类元信息句，防止模型以为"对方发过我没看到的消息"。

### 发现的问题：`COMMITMENT_HINTS` 与 `REMEMBER_PROMISE_STRONG` 漂移
分类用的强约定词含 **"约好 / 我们约 / 承诺"**，而**检测门**用的词表没有 →
`"我们约好九点见"` 能被分类成 `promise`，**却过不了检测门 → 不写记忆** → 表现就是"**答应了却没记住**"。
实测 4 个约定句漏 1 个。

### 修复
1. `COMMITMENT_HINTS` 补 `约好 / 我们约 / 承诺`（只加不删）；
2. `detect_commitment()` 末尾**再兜一层** `REMEMBER_PROMISE_STRONG`（词表以后漂移也不漏）；
3. 新增**一致性回归护栏**：凡分类为 `promise` 的句子必须过检测门。

### 验证 28/28
约定 4/4（修前 3/4）+ 四条回归护栏 + 一致性断言；画像 4/4；分类三类；会话键；
清洗（69 字 → 26 字，保留真记忆）；**托管四种情形**（True / 防抖不重调 / False / 用户关开关时强制 False）；
桥缺失降级（不抛异常、保持未同步、组装不崩）；委托事实（走 `inject_for_event`）。
**回归 498/498。**

### 留给 deepmemory 轮的观察
deepmemory 的记忆条目格式含 `[记忆 1/5 | 事实 | 日期 | 相关度 0.82]` 前缀，由记忆插件自己写进请求。
**待实测**：模型是否会把这些标注复述进回复。→ 审 deepmemory 注入模块时验。
