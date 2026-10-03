# alpha-0.87 —— 状态页瀑布流 + {穿搭} 占位符 + 日程/穿搭页三栏改造

> 回应四条要求：① 状态页「心事/最近余波/语气走廊/演化节拍记录」同列卡片间有莫名空隙；
> ② 穿搭给一个占位符；③ 日程页/穿搭页也分左中右三栏（右栏配置）；④ 日程/穿搭“更像我”的实时调整（待设计确认）。

## 变更

1. **状态页改瀑布流**（`dash-grid` 从 grid 改为 CSS `columns: 320px 4`）：
   卡片竖向连续堆叠、短卡紧跟下一张，**没有行高导致的空洞**；列宽按容器自适应、卡片不挤扁；
   最近余波/互动涟漪标题加「最多 3 条」上限提示（预留位语义明确）。
2. **新增 {穿搭} 占位符**（模板注入链 15 → 16）：
   - `wardrobe.py` 新增 `build_wardrobe_anchor(outfit)`：当前穿着 + 理由 + 语气提示（不主动晒）；
   - `main.py` `_anchor_values` 加 `values["wardrobe"]`（受 `wardrobe.enabled` 控制）；
   - `intercept.py` `TEMPLATE_PLACEHOLDERS`/`TEMPLATE_ORDER`/`DEFAULT_TEMPLATE` 加 `{穿搭}`（紧随 {日程}）；
   - 前端穿搭页占位符卡改为真实 {穿搭} 描述。
3. **日程页三栏**：左=未来规划+延误日程（panel 列表）｜中=当天日程（可编辑+添加+一键生成）｜
   右=日程设置（总开关+日程模型下拉+说明）。
4. **穿搭页三栏**：左=衣柜（列表+添加）｜中=当前穿搭（编辑+保存）｜右=穿搭设置（总开关+说明）。

## 测试

- `smoke_story_takeover.py` 95 项（新增：穿搭占位替换；mock 补 wardrobe_store 修复 _anchor_values 中断）
- `verify_057_pages.js` 81 项（新增：穿搭三栏/总开关在右栏、日程三栏）
- `smoke_story_smart` 28 / `ui_state` 14 / `intercept` 3 / `log` 10 / `verify_045` / `propagate` /
  `scan_story` 0 / `verify_046` 31 全绿
- 视觉自检：状态页瀑布流（iframe 1000）、日程页三栏、穿搭页三栏截图核对
