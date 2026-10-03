# alpha-0.106（主动对话「念头引擎」+ 通用 bug 修复）

## 主动对话升级（非雷同实现）

- **由头引擎（inspiration.py）**：主动消息不再靠"5 路素材随机拼一句"，而是由头生命周期管理——
  汇集持续源（状态/日程/记忆/见闻/梦）、事件源（早晚安/三餐关怀/约定后续）、登记源（外来模块可
  `register_inspiration_source()` 注入"可主动提的事"）→ 只在**好时机（窗内+配额+新鲜度）**挑一条最重要的提；
- **时段配额**：早晨/白天/傍晚/深夜 四段各限次数（`proactive.daypart_caps_json` 可配；深夜默认 0 不半夜打扰），
  与每日上限并存；
- **两级裁决合一**（一次 LLM 调用）：先判"值不值得发、会不会像打扰"，不值得输出 `:NO:` 静默；值得才组织自然表达；
- **克制日志**：每次候选记录（由头/重要性/裁决结果/是否发）进面板；
- **关系适配**：亲近度低 → 只允许高重要性由头，越高越敢提；
- 发送失败不消耗由头（下轮重试）；已提过去重（今天不重复同由头）；
- 主动消息改**关闭思考 + max_tokens=400**（快、不扰动主链）；主动页右栏新增「时段配额(JSON)」设置。

## 通用 bug 修复（自主测试发现）

1. **`token.py` 遮蔽 Python 标准库 `token`**（污染 logging/tokenize，导致任意深 imports 可能崩）——
   已重命名为 `token_usage.py`（TokenStore 接口不变，main import 更新）；
2. **跨午夜"深夜"时段桶失效**：原 `(23:00,05:59)` 区间 `lo>hi` 永不命中 → `daypart_bucket` 改为单独判定跨零点；
3. **注释雷同误报**：inspiration.py 的 utf-8 编码头命中扫描器 → 移除（Python3 默认 utf-8）。

## 验证

- 新增 smoke_inspiration（时段桶/由头收集/去重/配额计数）10 项全过；
- takeover 95、smart 28、ui_state 14、intercept 3、log 10、autoplan、verify_045、
  chat_text 35、雷同扫描 **0**、verify_057 85、verify_046_nav 31、compileall 全绿。
- 部署（/MIR 无旧 token.py 残留）、备份 alpha-0.106 完成。