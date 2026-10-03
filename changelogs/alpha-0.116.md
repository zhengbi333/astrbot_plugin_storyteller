# alpha-0.116

## 修复：记忆联动「未检测到」根因（实锤）

- **根因**：AstrBot v4.27 以 `data.plugins.<插件名>` 命名空间导入插件（`core` 在 sys.path，`data/plugins` 不在），storyteller 桥接用的顶层导入 `from astrbot_plugin_deepmemory...` 必然 ModuleNotFoundError，被 `_get_memory_bridge` 静默吞掉 → 记忆页恒显「未检测到」。（0.62 起该链路从未真正生效。）
- **修复**：`_import_deepmemory_bridge_module` 双路径导入（`data.plugins.astrbot_plugin_deepmemory.core.bridge` 优先，顶层名回退兼容旧 AstrBot/开发桩）；`_memory_bridge_status()` 分级诊断（未安装 / 已加载但桥接未开启 / 联动正常）不再吞错。
- **识别接口（用户要求）**：deepmemory alpha-0.74 新增 `bridge_status()` 只读探活（availability/版本/协同配置摘要）；记忆页新增「联动状态」展示板卡片（状态色块：正常绿/桥接未开启橙/未检测红）+「检测联动」按钮 + 精确原因与详情。

## 修复：主动消息「发了没被记录」（时间线断档）

- 主动对话走 `context.send_message` 直发，不经主链 → 记忆插件的 `on_llm_response` 记录不到 Bot 侧。
- 发送成功即 `record_visible_turn(role="bot")` 回填记忆时间线（`_note_proactive_sent`），与接管模式 `_note_bot_reply` 同机制；失败仅记日志不影响发送。

## 防御：平台回显「自己发的消息」双保险

- `_is_self_message`（sender==self_id）识别：storyteller 观察（不记互动/画像）、防抖（不收集）、主链拦截（静默阻断防回自己）；deepmemory 捕获（不把 Bot 消息当用户消息，防角色错位）。
- 默认平台不上报自身消息，此为保险；对第三方记忆类插件的捕获行为无影响。

## 其他

- README 补「记忆」19 选项卡清单与记忆页说明。
- 记忆页「联动状态」卡 + 检测按钮（.btn.mini 小按钮样式）。