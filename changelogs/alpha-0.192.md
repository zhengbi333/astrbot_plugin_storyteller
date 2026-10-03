# alpha-0.192

## 元数据修正：`metadata.yaml` 的 repo 字段（占位地址 → 真实仓库）

- **问题**（通读全部项目文档时发现）：工作区两个插件的 `metadata.yaml` 里 `repo:` 仍是脚手架占位 `https://github.com/example/<plugin>`，只有 `final/` 发布副本是正确的 `zhengbi333` 地址。
- **影响**：AstrBot 插件管理页展示的「来源仓库」不正确，插件市场/一键更新无法据此定位真实仓库（功能本身不受影响）。
- **修正**：
  - `astrbot_plugin_storyteller/metadata.yaml`：`repo: https://github.com/zhengbi333/astrbot_plugin_storyteller`
  - `astrbot_plugin_deepmemory/metadata.yaml`：`repo: https://github.com/zhengbi333/astrbot_plugin_deepmemory`
  - 同步到部署目录（`C:\Users\<用户>\.astrbot\data\plugins\...`）。
- **说明**：deepmemory 本次只改这一个字段，版本号仍为 `alpha-0.81`（其功能与 changelog 不变）；storyteller 按流程 bump 至 `alpha-0.192`。
- **未推送 GitHub**（用户要求暂停推送）：本地与部署目录已更正，`final/` 副本此前已是正确地址，无需改动。
- **验证**：两处 metadata 的 repo 字段与 `final/` 发布的安装地址一致；storyteller 版本三处（metadata / `__init__.py` / README）同步为 `alpha-0.192`。
