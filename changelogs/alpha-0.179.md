# alpha-0.179

## 修复 0.178 引入的加载失败：main.py 缺少 `import re`

- **错误**：0.178 在 `main.py` 新增生图意图分层的模块级/类级正则常量（`_IMAGE_ASK_RE = re.compile(...)`、`_IMAGE_WEAK_SIGNAL = re.compile(...)`），但 main.py 原本没有 `import re`——类定义时即抛 `NameError: name 're' is not defined`，**插件重载失败**（用户发现，最低级失误）。
- **修复**：main.py 顶部补 `import re`。
- **自查（本次一并加固）**：
  - 新增 AST 扫描脚本：全插件 31 个 .py 文件检查「使用了 re/json/time/asyncio/random/math/uuid/datetime/pathlib/typing/base64/hashlib/copy/threading/collections 但未从顶层导入」——**0 遗漏**；
  - `py_compile` 6 个改动文件通过；
  - **AstrBot 真实环境全模块导入冒烟**（backend/app + 插件目录，按加载顺序导入 30 个模块，含 `main`）——成功，`PLUGIN_VERSION = alpha-0.178`（冒烟后升 0.179），LLM 工具注册日志正常。
- 教训：新增用到标准库的文件/位置，先核对文件头部 import；发版前跑「导入冒烟 + 扫描」两道闸（后续发版默认步骤）。
