# alpha-0.270

## P0-1 群聊工具隔离

**问题**：群聊里她也能看到 `toolbox_fs_write` / `toolbox_python` / `toolbox_shell_run`。

权限门其实已经能挡住（非管理员会被拒），但：

- 模型**看得见**就会尝试调用 → 白花一轮 → 还会对群友说「我做不了」；
- 群友说「帮我写个文件」属于**提示注入**的经典入口，多一层风险。

## 做法

**群聊里直接不给这 13 个工具**（不是拒绝调用，是根本不出现在工具列表）：

```
fs_write / edit / doc_write / doc_export / python / shell_run
download / task_start / delegate / parallel / archive / learn / send_file
```

`send_file` 也挡了 —— 它虽只读，但能把**工作区里已有文件**发到群里，属于信息泄露面。

## 最关键的坑：缓存键

```python
# 改前
key = (True, tuple(sorted(allow)))
# 改后
key = (True, bool(is_group), tuple(sorted(allow)))
```

**如果只过滤不换键**：私聊先调一次 → 缓存里是「含写工具」的集合 → 群里再调 →
**命中私聊缓存**，隔离形同虚设。这是本轮最容易踩的地方，测试 D 组专门盯它。

## 双重保险

即使模型凭记忆硬调（不查工具列表直接发 `tool_calls`），执行侧也会拦：

```python
if name in _GROUP_BLOCKED_TOOLS and self._is_group_event(event):
    return {"ok": False, "status": "blocked",
            "message": "群聊里不能改文件或执行代码；需要的话请主人私聊我。"}
```

## 验证（`audit_87_group_isolation.py` 23/23）

- **A**：清单含 13 个写类工具，且**不含**只读工具（`fs_read`/`fs_list`/`web_search`）；
- **B**：`_is_group_event`：群→True、私聊→False、**无 event→True**（宁严勿松）；
- **C**：群聊工具集不含写类、保留只读；私聊仍有全部；
- **D**：**先私聊后群聊，群聊仍被过滤**（缓存不串）、再切回私聊仍完整；
- **E**：群聊里硬调 `fs_write` → 返回 `status=blocked`，文案说清原因。

## 已知边界

- 判定依赖 `unified_msg_origin` 里的 `Group`/`Friend` 字样，以及 `message_obj.group`；
  两种都没有时**按群聊处理**（宁可少给能力，不可误开放）；
- 群聊里她仍然能**读**文件（`fs_read`/`fs_list`/`fs_search`）—— 这是有意的：
  她要能看工作区的资料才能聊；如果连读也不该有，把这三个也加进清单即可。
