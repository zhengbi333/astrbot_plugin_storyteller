# alpha-0.269

## 修两处「吞掉关键结果」的静默失败

### ① `models.py`：tool_calls 写入失败被静默吞掉

```python
try:
    result.tool_calls = ordered
except Exception:
    pass        # ← 工具调用整个丢失，外面完全不知道
```

真机表现：**她收到了工具，但一次都没调**。
现在失败会写进 `_diag.log`，一眼能看出"模型是想调的，被我们丢了"。

### ② `reply_buffer.py`：表情包挂载失败被静默吞掉

```python
try:
    chain.file_image(seg["path"])
except Exception:
    pass        # ← 图没了，文字照发
```

用户可以接受"图没发出去"，但不能接受"她说发了、你什么都没收到、日志里也没有"。
现在失败写 `_diag.log`。

## 关于「318 处静默失败」的更正

上一轮体检报了 318 处，但**这个数字被高估了**。逐个看下来，大部分是合理的：

- 清理资源失败（`proc.kill()` 抛 `ProcessLookupError`）→ 该 pass；
- 可选功能失败（穿搭/天气/图片尺寸）→ 不该阻塞回复；
- 只有**吞掉关键结果**的那类才是 bug：工具调用、发送、记忆写入、路径解析。

按这个标准，真正危险的**约 20~40 处**，不是 318。本轮先修最危险的两处。
