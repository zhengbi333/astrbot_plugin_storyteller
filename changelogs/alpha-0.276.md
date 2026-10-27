# alpha-0.276

## 施工图要求「先验证能不能观测」，答案是：能

查证结果：

```python
# models.py:477（早就写好了）
cached = min(prompt, max(0, int(
    details.get("cached_tokens") or u.get("prompt_cache_hit_tokens") or 0)))
return SimpleNamespace(input_other=prompt - cached, input_cached=cached, output=completion)
```

**两种字段名都认**（`prompt_tokens_details.cached_tokens` 和 `prompt_cache_hit_tokens`）。
所以「能不能看到缓存命中」——**能**。

## 但缓存数一路被丢掉了

```python
def record(self, *, source, task, model, input_tokens, output_tokens):   # 没有 cached
```

`models.py` 解析出来了，`main.py` 也累加进 `input_cached` 了，
但**记账那一步没有这个字段** —— 结果面板只看得到 input 总量，
分不清"这是新内容"还是"这是被缓存的前缀"。

## 本轮补三件事

**① `_diag.log` 每次生成后记录**

```
缓存观测: cached=812 other=210 命中率=79% system_chars=1523
```

**② `TokenStore.record()` 接受 `cached_tokens`**

存进 `total["cached"]`（**不额外加到 input**，因为 cached 本来就含在里面）。

**③ 主链两处调用把 `usage.input_cached` 传进去**

## 为什么这一轮不改 system 结构

施工图写的是「system 拆稳定段 + 动态段，稳定段字面逐字节一致」。
但那是**改变 prompt 顺序**，会影响效果，风险不小。

**先拿到实测命中率再决定**：

- 如果命中率已经很高（比如 > 60%）→ 说明现状的前缀其实被缓存了，**不用改**；
- 如果接近 0 → 说明每轮都在重算，那时再动结构，有数据支撑。

这符合施工图自己写的前提：「**先验证**，不透传则降级」。

## 验证（`audit_92_cache_observability.py` 14/14）

- **A** 解析层：`cached_tokens` 认、平铺的 `prompt_cache_hit_tokens` 也认、
  没有字段时 cached=0/other=全部、cached 不超过 prompt（4 种情况）；
- **B** 记账层：`total["cached"]` 记上了、input 仍是全量（不重复相加）、
  不传 cached 时不留脏字段；
- **C** 接线：`_diag` 里有缓存观测、命中率、system 长度；主链两处传了 `cached_tokens`；
- **D** 本轮边界：`final_system` 的拼装顺序**没动**。

## 下一步（看真机数据再定）

重载后随便聊几条，看 `_diag.log` 里的「缓存观测」：

- 如果 `cached` 稳定在几百以上 → P1-6 视为**已达成**（现状已经吃到了缓存）；
- 如果一直是 0 → 我再动 system 结构（把动态部分挪到末尾）。

**这就是为什么我不急着改结构** —— 没有数据支撑的重构，可能就是白改。
