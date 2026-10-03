# alpha-0.7（2026-08-08）

## 变更

- **修复插件重载失败（Formatting field not found in record: 'plugin_tag'）**：
  - 根因：插件日志沿 logger 链传播到 AstrBot 日志 handler 时，AstrBot 为自身日志注入
    `plugin_tag`/`short_levelname` 等字段的 filter 不会作用于插件记录；上一版的文件日志
    模块未补齐这些字段，导致 AstrBot 日志格式化直接抛错、插件初始化中断。
  - 修复：日志模块新增字段注入 filter（`_EnricherFilter`），为每条记录补齐
    `plugin_tag`/`short_levelname`/`astrbot_version_tag`/`source_file`/`source_line`/
    `is_trace`/`ansi_prefix`/`ansi_reset`（与「为你篆刻的历史」同策略）。
  - 已验证：模拟 AstrBot 完整格式化器输出正常，插件可正常加载。

## 说明

- 版本备份：工作区 backup 目录下的 `astrbot_plugin_storyteller_alpha-0.7`。
