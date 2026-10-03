# alpha-0.8（2026-08-08）

## 变更

- **修复保存/上传完全失效（POST 请求不到后端）**：
  - 根因：插件 Web API 的请求对象存在两条调用路径——旧路径绑定 `astrbot.api.web.request`，而当前 AstrBot 的
    `call_request_view` 路径绑定的是面板运行时的 quart 风格请求代理（`astrbot.dashboard.asgi_runtime.request`）。
    上一版代码只使用了 `astrbot.api.web.request`，在该路径下 `request.json()` / `request.files()` 会抛
    「request is only available inside a plugin Web API handler」，导致所有 POST 接口 500、GET 正常
    （GET 接口不使用请求对象，所以此前「读取外观」一直成功而「保存外观」从无记录）。
  - 修复：请求对象三级回退（asgi 运行时代理 → astrbot.api.web → quart），JSON 解析、上传文件读取、
    落盘均兼容三种来源；已用模拟 asgi 代理验证 json/files 解析正确。
- **前端资源版本号升至 ?v=0.8**。

## 说明

- 后端 API 结构不变。
- 版本备份：工作区 backup 目录下的 `astrbot_plugin_storyteller_alpha-0.8`。
