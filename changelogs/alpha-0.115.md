# alpha-0.115（新增「记忆」选项卡 + 记忆架构透明化）

## 背景
- `{记忆}` 占位符/素材的来源是**外部插件【为你篆刻的历史】（deepmemory）**——本插件无自有记忆库，通过桥接层取用。
- 此前无"记忆"页面，用户看不到记忆内容与联动方式（架构不透明）。

## 新增「记忆」选项卡（第 19 页，位于内心/主动之间）

- **左栏：最近记忆**（来自 deepmemory `list_recent_memories`，只读，无桥时提示安装）；
- **中栏：近期时间线**（deepmemory `get_timeline`）；
- **右栏：记忆联动设置**（managed_injection / 约定提取 / 画像采集 / 嵌入、画像、约定模型——自拦＆改页迁入）+ `{记忆}` 来源说明（放行时记忆插件注入；接管时本插件 compose_injection 生成完整记忆包；未安装则占位符留空，不影响其它模块）。
- 后端新路由：`GET memory`（只读拼装）。

## 流程（`{记忆}` 从哪来 / 怎么写 / 怎么注入）

- **写入**：对话中检测约定/愿望（detect_commitment）→ deepmemory 沉淀；画像/关系记忆回写。
- **注入**：`_anchor_values["memory"]`（6 条 hint）→ 接管的 `_compose_memory_text`（完整记忆包）；放行由 deepmemory 托管注入（managed_injection）。
- **旁路消费**：主动由头（记忆/未完成）、日程素材、日记素材同源。

## 验证
- schema、compileall、verify_046_nav **31**（19 项适配）、verify_057 **88**（19 项）、inspiration 11 全绿。