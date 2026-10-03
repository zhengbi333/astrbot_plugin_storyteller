# alpha-0.11（2026-08-08）

## 变更

- **修复界面渲染崩溃（事件绑定失效的根源）**：
  - 诊断面板捕获到确切错误：`Cannot read properties of null (reading 'addEventListener') @ bindAppearanceEvents`；
  - 根因：背景板开关的绑定代码按 `#canvas-toggle`（id）查询，但模板元素只有 `data-canvas-toggle` 属性（无 id），
    返回 null 后 `addEventListener` 抛异常；
  - 该崩溃发生在主题事件绑定之后、文件选择框事件绑定之前，导致：
    - 点击主题后重渲染崩溃（旧版本还会顺带阻断保存请求）；
    - 上传弹窗正常（label 原生行为），但选中文件后的 change 事件从未绑定，选完毫无反应；
    - 滑块、背景板开关、清除按钮等事件全部失效。
  - 修复：按 `data-canvas-toggle` 属性选择并做空值保护；已核对全部控件选择器与模板一一对应。
- 页面资源版本参数升至 `?v=0.11`。

## 说明

- 保存链路此前已打通（alpha-0.8 请求对象修复 + alpha-0.10 render 隔离）。
- 版本备份：工作区 backup 目录下的 `astrbot_plugin_storyteller_alpha-0.11`。
