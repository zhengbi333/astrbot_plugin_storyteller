# alpha-0.100（内心模块重构）

按用户拍板实现：三栏布局 / 保留三类内容 / 手动生成+删除 / 后台定时+手动搜索（Tavily 已适配）。

## 页面（内心页三栏）

- **左栏**：日记（每天一篇的心事）+「写一篇」手动生成按钮（复用深夜写日记逻辑）。
- **中栏**：梦境 +「生成梦境」；思考 +「冒个念头」——每条记录带时间与「删除」按钮，随手清理。
- **右栏**：见闻（列表 + 「刷一刷」一键搜新鲜事 + **手动搜索框**：输入关键词→搜索→整理成见闻保存）；
  下方「内心设置」展示板：内心模块总开关、梦境模型、思考模型、搜索整理模型、
  **自主浏览（无聊自己刷）**开关与间隔（默认 6 小时）。全部走统一 .setting-card 卡片 + 自动保存。

## 后端

- `MindStore`：新增 `delete(kind, index)`（越界/类型非法返回 False）、`meta_get/meta_set`（browse 间隔持久化）；`_meta` 随 mind.json 存取。
- `mind.browse(plugin, *, force)`：自主浏览统一入口——按 `search.browse_interval_hours`（默认 6）节流；
  搜索"最近有什么新鲜事" → LLM 整理成见闻 → 存入 + 更新 last_browse_at；无结果/无 key 时不消耗间隔；`force=True` 供手动。
- `main._mind_loop`：每 30 分钟轮询内加自主浏览（受 mind.enabled + search.browse_enabled + 间隔限制，失败静默）。
- 新路由：
  - `POST mind/generate` {kind: dream|think|diary}：手动生成（复用 dream/think/_write_diary，创作类保留思考）；
  - `POST mind/search` {query}：手动搜索（search_and_think → add_sighting），失败返回具体原因（引擎/API Key）；
  - `POST mind/delete` {kind, index}：删除一条。
- schema：mind 大类新增 `enabled`（内心模块总开关，默认开）+ 保留 dream/think_provider_id；
  search 大类新增 `browse_enabled`（默认开）、`browse_interval_hours`（默认 6，hint 写明利害：太短机械烧 token、太长见闻更新慢）。

## 交互细节

- 所有生成按钮进入忙碌态显示秒数（runWithBusy），失败 toast 具体原因；
- 删除/生成后局部刷新（不整页重载）；搜索框空关键词拦截；
- 搜索无结果提示「检查设置 → 搜索的引擎与 API Key」。

## 验证

- schema JSON 校验、compileall、verify_046_nav 31、verify_057 84、takeover 95、smart 28、
  ui_state 14、intercept 3、log 10、autoplan、verify_045、propagate、雷同 0、chat_text 35 全绿。