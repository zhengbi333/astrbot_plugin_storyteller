# alpha-0.233

## 25 模块深度自检 · 第 24 轮：debug 调试 —— 修掉「配置保存日志明文写入 API Key」

### 🔴 问题：保存配置时整段配置（含密钥）被写进日志
`page_api.py` 里保存配置后打印了**整段模块配置**：
```python
logger.info("[Storyteller] 配置已保存: module=%s values=%s", module, current)
```
**实测证据**：用户的 `storyteller.log`（109KB / 538 行）**行 76、78** 有两处明文密钥：
`配置已保存: module=image values={'enabled': True, …, 'api_api_key': 'sk-…'}`。

**风险**：用户排障时常把日志贴到群里/issue → **密钥随日志泄漏**；日志还会被备份或同步到别处。

### 修复
新增 `_mask_config_values()`：键名含 `key`/`token`/`secret`/`password`/`credential` 的字段
只保留 **`<已设置 N 字符>` / `<未设置>`**，非敏感字段保留原值（便于排查）。配置保存日志改用它。
实测：`api_api_key: 'sk-abcdef1234567890'` → `<已设置 19 字符>`；`api_base_url` 原样保留。

### ⚠️ 已落盘的历史记录（不擅自删用户数据，如实告知）
那 2 行是修复前写入的。建议：① **轮换该 API Key**（最稳妥）；② 或自行删除该日志文件。

### 验证 12/12
- 脱敏：28 个源文件的 logger 语句无凭据拼接；保存日志确实调用脱敏；脱敏行为三态正确
- `logs` 端点：返回 `file/logs/path`，读到 200 行不崩
- 自检 23 项结构完整、无重复 key
- 前端 6 个诊断端点（`diag/runtime`、`diag/checks`、`diag/check`、`diag/run`、`diag/llm_test`、`logs`）**全部被调用**
- **回归 498/498**

### 我自己的两次取样失误
① 断言写 `lines` 键（实际端点用 `logs` 键）；② 路由提取正则按 `routes.get("x")` 写，而项目用**元组列表**注册 → 拿到空列表。
→ 教训：**断言失败先回到真实实现取值，再改断言**。
