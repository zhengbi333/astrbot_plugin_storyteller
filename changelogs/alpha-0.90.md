# alpha-0.90 —— 超时根因建议 + 日程「当天日程」转盘改造（修复重复渲染）

> ① 用户再报超时：日志实为 **private_companion 插件调 SiliconFlow DeepSeek-V4-Pro**（非本插件）
>    `APITimeoutError: Request timed out`——进一步印证「非流式长输出在 SiliconFlow 系慢、
>    超过 120s 客户端超时」是**平台侧问题**（与模型/网络无关；provider_stats 里同模型
>    72 次全部 1~19s 完成）。**建议**：在 AstrBot 管理后台把 SiliconFlow 该 provider 的
>    「超时时间」调大（如 300s），对本插件与 private_companion 都有效；
>    本插件侧保持「设置 → 模型配置 → 流式直连生成」默认开（流式规避）。
> ② 「当天日程」重复渲染 bug：模板同时渲染了 `#s-rows`（entryRows）与 `entryRows || ...`
>    两遍 → 上下两段长列表。改造为**转盘展示**：只显示此刻（高亮）+ 前一条/后一条（虚化），
>    其余折叠；「展开全部」切换为可编辑列表；修复 now 时间比较（HH:MM 截取，避免日期前缀字符串比较）。

## 变更

1. **转盘展示**（`#s-marquee`）：`sched-now`（此刻，青绿底+▶此刻）/ `sched-prev`/`sched-next`
   （虚化 opacity 0.45）/ `sched-other`（display:none）；「展开全部 ←→ 收起为转盘」按钮切换；
2. **修复重复渲染**：`#s-rows` 只渲染一份 entryRows（编辑态），展示态由 marquee 负责，
   不再出现"上半输入框密集、下半带备注"的两段；`renderScheduleRows`/`bindScheduleRows` 拆分
   （展示态默认不绑定编辑，展开时绑定）；
3. **修复此刻判断**：`diag.now` 取 `HH:MM` 片段再与 `start/end` 比较（此前带日期前缀字符串比较
   导致此刻匹配错位）。

## 测试

- `verify_057_pages.js` 84 项（新增：s-marquee / s-toggle / sched-now 断言；stub 补 schedule 数据）
- 全量：takeover 95 / smart 28 / ui_state 14 / intercept 3 / log 10 / autoplan / verify_045 /
  propagate / scan 0 / nav 31 全绿
- 视觉自检：转盘「此刻=09:00-11:00 写报告」高亮、前后虚化截图核对
