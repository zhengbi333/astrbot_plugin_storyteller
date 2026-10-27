# alpha-0.257

**根因不在工具描述，在一条静默失效的降级路径。**

## 三条「工具永久失效」的路径

### ① 工具列表为空被当成「provider 不支持 tools」

```python
# models.py 旧代码
if not tools:
    raise _ToolsUnsupported("没有可用工具")
```

`_ToolsUnsupported` 的语义是「提供方拒绝原生工具」，调用方收到后会把
`_native_tools_unsupported` 置 True。**于是"这一次没有工具"被记成了"这家 provider 不支持工具"。**

改成 `_DirectUnavailable("本次没有可用工具")` —— 只是这次没有，不污染降级开关。

### ② 400/422 一律当「不接受 tools」

参数错误（`stream_options`、`tools` 格式、长度超限）也会返回 400，但都会被判成"不支持原生工具"。
现在检查报文：**只有明确出现 `tool` / `function` 字样才算**，其余按普通上游错误处理。

### ③ 降级开关是永久的

```python
self._native_tools_unsupported = False   # 只在 __init__ 置 False
...
self._native_tools_unsupported = True    # 一处误判 → 整个进程再也没有工具
```

**只有重启插件才恢复。** 现在加了冷却：置位时记 `_native_tools_retry_at = now + 600`，
10 分钟后自动重试原生工具。

## 这解释了真机的现象

```
她收到「帮我做个 word 文档」
  → 没有工具可用（因为降级了）
  → 只能聊天
  → 人格插件自己的生图模块命中「做…」→ 画了一张图
  → 「给你画好啦～」
```

**生图模块不走 tools**，所以它是唯一还能"动手"的路径 —— 于是所有"干活"请求都被它接走了。

## 验证

- `models.py` 三处改动已确认落在代码里；
- `main.py` 的 `_native_tools_retry_at` 三处（初始化 / 判断 / 置位）都在；
- 全量回归 690/690、一键验收 47/47。

## 已知边界

- 冷却期（10 分钟）内仍然走纯文本生成 —— 如果 provider 真的不支持 tools，这 10 分钟是"白等"；
- 真正的判定要靠报文关键词，个别 provider 的报错措辞可能躲过检查；
- 这次的修法只保证「不会因为一次误判就永久失去工具」，**不保证工具一定能调对** ——
  描述质量那部分（0.256）仍然重要。
