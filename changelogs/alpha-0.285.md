# alpha-0.285

## 修一个真缺口：能力页的上限输入框是死的

## 怎么发现的

用户让我自查「新功能放在哪、面板有没有控制项、可交互性怎么样」。我写了个验证脚本，
发现两件事：

### ① 认知侧：全通

- 9 个配置键都在 `_allowed_keys` 白名单里（写入不会被拒）；
- `describe()` 输出里 `actions` 组 9 项全在，默认值读对、说明不为空；
- **用临时文件实测写入链路**：改一个开关 → 文件里真的有 → `describe()` 读回新值；
- 非法键被拒、字符串 `"false"` 会被 `_coerce` 转成 `False`。

### ② 陪伴侧：**输入框是死的**

`capabilities` 那 12 个 `*_daily` 被 `EXCLUDED_MODULES` 排除在设置页外，
所以能力页那个数字输入框是**它们在面板上的唯一入口**。

上一轮我只加了渲染（`data-cap-limit`），**事件绑定没加上**
（当时脚本判断"绑定已有"是错误的，实际匹配到的是另一处旧代码）。

结果：输入框能显示，改了没用。

## 修法

```js
document.querySelectorAll("[data-cap-limit]").forEach((el) => {
  el.addEventListener("change", async () => {
    const key = el.getAttribute("data-cap-limit");
    const value = Math.max(0, Math.min(999, parseInt(el.value, 10) || 0));
    await apiPost("config/module/update", { module: "capabilities", values: { [key]: value } });
    setTimeout(() => loadCapabilities(), 350);   // 刷新确认
  });
});
```

失败会写 `diagLog` 并把边框变红，成功变绿。

## 验证

| 脚本 | 结果 | 覆盖 |
|---|---|---|
| `audit_106_selfcheck_panel.py` | **41/41** | 白名单、describe 值、写入函数、前端接口、8 个工具 docstring |
| `audit_107_selfcheck_write.py` | **31/31** | **用临时文件实测写入**：9 键写入、文件落盘、describe 读回、非法键拒绝、类型纠正 |
| `audit_108_selfcheck_cap_limit.py` | **25/25** | 渲染、绑定、12 个日限键命中、`node --check` |

## 一句实话

这三个脚本我一开始都写错了（查 `poke_enabled` 而不是 `actions.poke_enabled`、
查 `description` 而不是 `label`、`update()` 少套 `values`）——
**错的是测试，不是功能**。但正因为写错了才发现「输入框没绑定」这个真问题。
