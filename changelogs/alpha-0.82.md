# alpha-0.82 —— 视觉审查修复：顶部导航不再截断、卡片词不拆、标题不折

> 用无头浏览器（Edge headless + 本地 mock 桥）真实渲染插件页进行**视觉自检**，
> 发现并修复三处影响观感的问题（此前仅靠断言验证、无视觉回归）。

## 变更

- **顶部导航不再横向滚动截断**：`.topnav` 从 `overflow-x:auto`（18 选项卡只能看见前面 10 个，须拖动）
  改为**顶部文字行 + 导航整行换行**（`flex-wrap`，`order:3` 独占第二行）；
  所有选项卡**全部可见**，窄屏自动换行成多行，宽屏依旧整齐。
- **长说明卡跨全宽**：「状态怎么随对话/事件变」从 1/4 窄卡改为 `.dash-wide`（`grid-column:1/-1`），文字舒展。
- **标题不再折断**：设置卡标题去掉"（分钟）"单位（挪入 hint）；`field-key`（英文键名）`white-space:nowrap`
  不再被折行错位；`field-title` 允许 `overflow-wrap:anywhere` 防溢出。
- **词不拆断**：`.dash-grid .panel .hint` 改 `break-word`；`.panel-head` 允许换行、hint 独立行
  （窄卡里"电量""素材"等词不再被拆成两半）。
- 底部说明条限宽（max-width 860px）居中，不横贯整屏。
- 另建 `dev/ui_preview/`（mock 桥 + 真实 app.js/style.css）作为**后续视觉回归工具**，
  可 `preview.html?tab=<键>` 直接截任意页。

## 测试

- `verify_057_pages.js` 74 项 / `verify_046_nav.js` 31 项 / 语法（app.js + 全部 py）全绿
- 视觉自检：暗/浅色 × 1280/1440/900 共 5 张截图核对通过
