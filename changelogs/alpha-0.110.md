# alpha-0.110（目标用户管理 + 节奏可视化）

## 修改

- **目标用户改为"添加/删除"管理**（左栏「目标用户」卡）：
  - 顶部输入 QQ 号 + 「添加」按钮；每条用户显示（上次主动/最近回应/今日已发）+「删」按钮；
  - 删除右栏的「想让她主动找的人」输入卡（单一入口、避免两处重复）；
  - 后端新路由 `POST proactive/targets`（add/remove，写 proactive.target_users 配置并即时生效）。
- **节奏可视化**（顶部总览条）：今日已发 N/上限（0=不限制）、当前是否在**免打扰时段**（⏸ 免打扰中 / 可发时段）。
- proactive_status 新增返回 `quiet_hours`/`quiet_now`/`max_daily`（前端直接展示）。

## 验证

- schema、compileall、verify_057 88、verify_046_nav 31 全绿。