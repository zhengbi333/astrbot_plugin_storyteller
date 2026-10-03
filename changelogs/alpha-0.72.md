# alpha-0.72 —— 人格库选择（AstrBot 人格库 + 下拉显示人格标题）

> 按您要求：一键生成的人格不再只读"当前默认人格"，而是枚举 **AstrBot 人格库**供选择；下拉显示**人格标题**（而非"默认人格——内容"样式）。

## 变更

- **读取 AstrBot 人格库**：`voice_personas` 优先枚举
  - `persona_manager.personas_v3` 列表；
  - 或 `get_personas` / `list_personas` / `all_personas` / `get_persona_list` 候选接口（兼容 await/同步）；
  - 逐个取「人格标题（name/title）」与「prompt（填充内容）」；
  - 取不到库时兜底读取当前默认人格（`get_default_persona_v3`，标记为"AstrBot 默认人格"）。
- **下拉显示人格标题**：选项文本=人格名称/标题（不再拼接人格内容）；选中后用该人格的 prompt 自动填入输入框再一键生成。
- 完全脱离记忆插件 personas（此前误用，已确认 AstrBot 人格库在 persona_manager 的 personas_v3/列表接口）。

## 测试

- `verify_057_pages.js` 57 项（人格库下拉显示多人格标题、不拼内容的断言）
- 部署差异 0
