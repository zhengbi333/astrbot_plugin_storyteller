# alpha-0.220

## 25 模块深度自检 · 第 6 轮：intercept 拦＆改 —— 修掉「接管走主链」从未生效的致命 bug

### 🔴 问题：默认介入方式的代码分支永远到不了

`on_llm_request()` 里原本是这样写的：

```python
if mode in (MODE_TAKEOVER, MODE_TAKEOVER_MAINCHAIN):     # 两种接管共用公共准备
    ... 生成中消息并入 pending / 会话搜索 / 承诺写入 ...
    self._sync_memory_managed(False)
    await self._takeover_reply(event, req, text, prompt, system_prompt)   # ← 无条件执行
    return
if mode == MODE_TAKEOVER_MAINCHAIN:                       # ← 死代码，永远到不了
    self._sync_memory_managed(True)
    await self._takeover_via_mainchain(event, req, text, prompt, system_prompt)
    return
```

而 `resolve_mode()` 的兜底、`_conf_schema.json` 的默认值、changelog 记载的"默认介入方式"
**都是「接管走主链」** → **所有用默认模式的用户，实际跑的都是「接管改换」**
（直连指定模型 + 阻断主链），与 UI 描述和当初"默认改接管走主链（拟人完整 + 零插件冲突）"的定夺都不符。

`_takeover_via_mainchain` 只被这一处引用 → **它从未被真正执行过**（尽管实现写得相当完整：
模板渲染、时间线去重、媒体保序脚本、记忆组装都在）。

### 取证
1. 全仓引用点只有 645 行（死代码）+ 1922 定义
2. `CHANGELOG.md` 明确记载该模式的设计意图与"默认改接管走主链"
3. 分派测试直接抓到：选「接管走主链」时 `_takeover_reply` 被调用、`_takeover_via_mainchain` 没有

### 修复
改成按模式分派：`接管改换 → _takeover_reply`（阻断主链）、`接管走主链 → _takeover_via_mainchain`（放行主链），
记忆托管状态分别为 `False` / `True`。

### 顺带修的两处一致性问题
1. **自检项模式默认值**：`intercept_status` 里默认写"接管改换"，而 schema/主链默认是"接管走主链"
   → 配置缺键时自检显示错误模式。改用 `resolve_mode()` 与真实链路同源。
2. **降级记录语义**：`_takeover_fallback` 的"放行主链"分支记成 `blocked=True`，但实际没阻断
   → 「拦＆改」页会显示成"被阻断"。已改为 `False` + note 写明"未阻断"。

### 验证
- **五种模式分派 24/24 通过**：监视 / 阻断 / 放行 / 接管改换 / 接管走主链，逐项核对
  谁被阻断、谁被注入、谁进哪条链路；总开关关闭完全不介入；`resolve_mode` 非法值兜底；
  **接管失败三态**（阻止主链与否、超时文案调用次数、记录的 blocked 标记与实际一致）
- **回归**：二十三批非真链 **498/498**；真链抽查 sim 11/11、工具 5/5、思绪 9/9

### ⚠️ 风险提示
`_takeover_via_mainchain` 修好后**第一次真正生效**（此前从未运行过），可能有未发现的边缘问题。
建议先用「接管改换」观察，试「接管走主链」时留意回复是否正常走主链管线。
