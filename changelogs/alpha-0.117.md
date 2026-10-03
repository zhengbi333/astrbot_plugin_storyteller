# alpha-0.117

## 主动消息写入 AstrBot 会话历史（你定夺的方案 A）

- **背景**：主动消息直发不经主链，此前只有 0.116 的 deepmemory 时间线回填；主链（会话 Main Agent）的 LLM 上下文直接读 `conversation.history`（`astr_main_agent.py` 1405 行实锤），故主链看不到主动消息。
- **实现**：`_archive_proactive_to_history(session_id, text)`——发送成功后经官方通道写入：
  - `conversation_manager.get_curr_conversation_id(umo)` 取当前会话；无会话则 `new_conversation(umo, title="主动消息存档")` 自动建档（兼容旧版签名 TypeError 重试）；
  - `add_message_pair(cid, user_seg, assistant_seg)` 写入消息对：user 侧为中性存档标记「[主动消息存档] 此刻并没有人说话，Bot 主动给用户发了一条消息，内容见 assistant 侧。」，assistant 侧为主动消息原文；
  - 效果：下一次用户发言时主链上下文带上这句 bot 主动消息，AstrBot 会话记录/WebUI 历史同步可见——等效「bot 在主链发过这句话」。
- **新设置项**：`proactive.archive_history`（bool，默认开）——主动页设置卡新增，关闭后只保留记忆回填。
- 与 0.116 双通道闭环：记忆插件 = `record_visible_turn(role=bot)`；主链/会话记录 = 会话历史。

## 测试

- smoke_bridge_import 20 → **31 项**（归档：有会话直写/无会话建档/旧签名兼容/开关关闭/无管理器静默/端到端双通道）。
- verify_057 主动页新增「写入会话历史开关」断言（93 → 94 项）。