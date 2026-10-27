# alpha-0.258

## 一、加「工具使用规范」（照 DSH 系统提示的写法）

人格插件截断主链后，**AstrBot 原本附带的工具说明也一起没了**。她只拿到 26 个工具名和描述，
没有任何"该怎么用"的指导，于是遇到"做个文档"就挑那个"画图并直接发送"（看起来更省事）。

新注入一段 6 条通用规范（**没有关键词表**，和 DSH 的做法一致）：

- 有工具能做的事就调工具，不要凭印象直接答
- 用户要**文件**（文档/表格/报告/纪要/清单/Word/Excel/PDF）→ 产出物必须是文件：
  用写文档的工具写、再用发文件的工具发。**画图不是文件，表情包也不是**
- 用户要看**画面**时才用画图/拍照
- 工具报错按原文改一版重试；连续两次同样错就停下如实说卡在哪
- 不确定的路径先列目录，别猜
- 做完一句话说结果，别把工具返回整段贴出来

## 二、加落盘诊断（`_diag.log`）

AstrBot 的日志在 GUI 里，日志目录只有个 0KB 的 watchdog —— 我看不到，所以一直在猜。

现在关键节点会写一行到 `plugin_data/astrbot_plugin_storyteller/_diag.log`：

```
生成前: tools=26 unsupported=False retry_at=0 model=deepseek-v4-flash
直连不可用: {'client': True, 'base_url': True, 'api_key': False, 'api_version': False}
降级触发(_ToolsUnsupported): 提供方不接受 tools 参数：HTTP 400 ...
```

**下次工具不生效，直接读这个文件就知道断在哪一环**，不用再猜。

## 三、判定依据（已查证）

- provider 配置里 `modalities = ['text', 'tool_use']` —— **模型本身支持工具**；
- api_key 不在 `cmd_config.json` 的 provider 条目里（在 provider_source 里），
  人格插件的直连需要从 provider 对象抠 `client.api_key` —— **抠不到就退回不带工具的通道**；
- 这就是为什么要加诊断：确认到底卡在"抠 key"还是"provider 拒绝 tools"。

## 四、验证

- 全量回归 690/690、一键验收 47/47；
- 注入位置已确认（`_TOOL_USAGE_RULES` 定义在 83 行，使用在 2463 行）。
