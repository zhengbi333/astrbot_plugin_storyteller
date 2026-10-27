# alpha-0.245

## 新增「外部行动记忆写入口」`note_external_event`

配合认知插件 0.7.0：认知完成 learn / 写文档 / 下载 / 发文件后，把"我做了什么"转告给人格，
由人格统一写入 deepmemory（`record_bot_action`，`self_action`）。

这样**记忆只有一个写入口**：措辞、去重、会话归属都由人格决定，认知不直接碰记忆库。

行为约定：

- **去重**：`kind + 文本前 80 字`，最近 80 条内重复的直接返回 `duplicate`；
- **不抛异常**：记忆桥缺失返回 `no_bridge`，写入异常返回原因，绝不把异常抛给工具执行路径；
- **带会话上下文**：沿用 `_session_ctx_dict(event)`，与既有记忆写入一致；
- **成功才记**：只有 `memory_id` 非空才算 `ok=True`。

## 验证

`_st_test/audit_65_link_bridge.py` 的 C 组（人格侧）：写入成功返回 id、source 正确、带会话上下文、
重复去重、无桥降级、写入异常被吞掉并给出原因。合计 20/20。
