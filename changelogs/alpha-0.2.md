# alpha-0.2（2026-08-08）

## 变更

- **修复设置页报错「不受支持的配置类型 boolean」**：`general.enabled` 的 schema 类型由 `boolean` 修正为 `bool`（AstrBot 支持的类型为 int/float/bool/string/text/list/file/object/template_list/dict）。此前该配置项会导致插件设置页加载报错。

## 说明

- 无行为变化；插件总开关默认仍为开启。
- 版本备份：工作区 backup 目录下的 `astrbot_plugin_storyteller_alpha-0.2`。
