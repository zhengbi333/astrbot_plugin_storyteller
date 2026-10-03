# alpha-0.93 —— 修复"卡生成中" + "穿搭页设置不保存"

> ① 一键生成仍卡"生成中"：根因是直连调用**没有单次限时**——流式/非流式在 AstrBot 客户端
>   内部等待（120s×N 次）+ 重试，前端按钮挂起。修复：**每次尝试限时 + 前端桥调用超时兜底**。
> ② 设置不能自动保存（穿搭页）：三栏改造后 renderWardrobe 漏调 `bindSettingsIn(view)`，
>   右栏「穿搭生成模型」下拉无保存绑定——已补。

## 变更

1. **单次生成限时**（`models.stream_timeout`，默认 120s，可配）：
   - `chat_text` 流式/非流式每次尝试都用 `asyncio.wait_for` 包住，超时立即放弃本次，
     不再无限等 AstrBot 客户端超时（其重试 5 次×120s 会拖死按钮）；
   - 流式失败自动重试（`models.stream_retry` 默认 1，共 2 次尝试），仍失败回退非流式；
   - 失败/超时记日志（哪次尝试、什么错误），便于排查。
2. **前端桥调用超时兜底**（`withTimeout`）：`apiGet` 150s / `apiPost` 180s，
   桥调用无响应时按钮恢复 + 明确提示"已终止等待"，绝不永远"生成中"。
3. **穿搭页保存修复**：`renderWardrobe` 补 `bindSettingsIn(view)`——右栏「穿搭生成模型」
   下拉现在改后自动保存（此前绑定缺失，改了下拉不落盘）。

## 测试

- `smoke_story_chattext.py`：流式聚合/首败重试成功/全失败(2 次)回退非流式/关流式走非流式/双失败抛异常
- 全量：takeover 95 / smart 28 / ui_state 14 / intercept 3 / log 10 / autoplan / verify_045 /
  propagate / scan 0 / verify_057 84 / nav 31 全绿；语法全绿
