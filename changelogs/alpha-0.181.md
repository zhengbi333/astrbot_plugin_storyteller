# alpha-0.181

## 修复「A1 上文生图」从不触发（QQ 实测暴露：ImportError 被静默吞掉）

- **症状**：0.178 上线的 A1（索图式短问+会话上文）从未生效——QQ 实测「你那边的云怎么样」→「给我看看？」**走了普通对话**（模型答"等会儿拍给你"），而不是按上文画云；
- **根因（实证）**：`_image_recent_user_text` 内 `from .debounce import _looks_command` —— `_looks_command` 在 debounce.py 中是 **`DebounceManager` 实例方法（904 行）**，模块级不存在 → 该行抛 `ImportError` → 被 `_resolve_image_intent` 的 `try/except: pass` 静默吞掉 → A1 永远拿不到上文；
- **修复**：改为实例调用 `getattr(self.debounce, "_looks_command")`（异常防御兜底），删除错误 import；
- **验证**：`py_compile` 通过；main 模块导入成功；`StorytellerPlugin._looks_image_ask("给我看看？")=True`、`("你在干嘛？")=False`（不误触发）；时间线数据（8 行含 role/occurred_at）与过滤链审查确认 A1 可正确命中最近用户发言。
- 附带说明：QQ 实测其余全部正常——「拍个照发我」规则命中生图（7.5s 出图并发送+写历史）、「你在干嘛？」接管+润色正常、云话题接管+润色正常、防抖智能判定（continue/release）正常、NapCat 已连接、deepmemory 时间线/托管注入正常。
