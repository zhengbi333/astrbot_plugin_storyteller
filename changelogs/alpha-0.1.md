# alpha-0.1（2026-08-08）

## 首版骨架

- 插件生命周期与数据目录初始化。
- WebUI 面板「故事面板」（`pages/storyteller-panel`），空灵简洁科技风：
  - 总览：品牌欢迎区与插件状态占位；
  - 外观：完整的外观控制。
- 外观控制（与「为你篆刻的历史」功能对齐，独立实现）：
  - 8 套空灵科技风配色主题：星穹（默认）/ 极光 / 月汐 / 银雾 / 深海 / 幽萤 / 绯夜 / 玄墨，每套含明暗两套变量；
  - 明暗模式：跟随系统 / 明亮 / 暗色；
  - 自定义主色、辅色，可覆盖主题默认值；
  - 背景板：颜色、开关、透明度（0-1）、模糊（0-60px）玻璃拟态；
  - 背景图片：上传（≤ 8 MiB，png/jpg/jpeg/gif/webp/bmp）、预览、清除；
  - 恢复默认外观。
- 后端 API：`/astrbot_plugin_storyteller/health`、`/appearance`、`/appearance/update`、`/appearance/reset`、`/appearance/background`、`/appearance/background/clear`。
- 外观配置持久化于 AstrBot 数据目录 `astrbot_plugin_storyteller/appearance.json`，与代码分离，更新插件不清数据。

## 说明

- 陪伴功能（对话托管、记忆联动等）将在后续版本逐步加入，届时按「为你篆刻的历史」的桥接接口接入记忆库。
- 版本备份：工作区 backup 目录下的 `astrbot_plugin_storyteller_alpha-0.1`。
