# alpha-0.16（2026-08-08）

## 变更

- **顶部导航严格居中**：导航条改为相对顶栏绝对居中（左品牌、右版本号宽度不再影响其位置）。
- **新增「设置」选项卡**（配置机制与「为你篆刻的历史」一致，独立实现）：
  - `general.enabled`：插件总开关——关闭后插件不再参与对话，**WebUI 面板仍可正常查看与设置**；
  - `general.page_animation`：界面切换动画开关；
  - 设置页按 schema 渲染（开关/数值/文本），每模块独立「保存 / 恢复默认」；
  - 配置持久化于 `<data>/config/astrbot_plugin_storyteller_config.json`（UTF-8-SIG，与 AstrBot 配置系统一致）。
- **页面切换动画**：选项卡/页面切换时淡入上移（0.32s 缓动），可在设置页关闭。
- 新增后端接口：`GET /config/schema`、`POST /config/module/update`、`POST /config/module/reset`。
- 页面资源版本参数升至 `?v=0.16`。

## 说明

- 设置保存在 astrbot 配置目录（与插件代码分离），重载插件后保留。
- 版本备份：工作区 backup 目录下的 `astrbot_plugin_storyteller_alpha-0.16`。
