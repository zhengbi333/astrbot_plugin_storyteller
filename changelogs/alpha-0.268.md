# alpha-0.268

## 现象

「守则」和「判定」两个页签一直停在「切换中…」，其它页正常。

## 根因：这两个函数只 return，没写 DOM

看别人怎么写的（沉默页）：

```js
async function renderSilence() {
  view.innerHTML = '<div class="loading">加载沉默…</div>';   // ← 自己写
  const data = await apiGet("silence");
  view.innerHTML = `...`;                                     // ← 自己写
}
```

我写的那两个：

```js
async function renderJudge() {
  const data = await apiGet("judge/stats");
  ...
  return html;        // ← 只返回，谁写？
}
```

而调用处是：

```js
if (state.current === "judge") await renderJudge().catch(...);
```

**返回值被直接丢弃** → 页面里除了我在 `render()` 开头写的「切换中…」什么都不剩。

## 修了什么

1. `renderJudge` / `renderActing` 末尾改为**自己写入 DOM**：
   ```js
   const view = $("#view");
   if (view) view.innerHTML = html;
   return html;
   ```
2. 两个**空状态提前 return** 的出口也补了写入（否则后端异常时会停在「切换中…」）。

## 验证

- `node --check` 通过；
- 自检：`view.innerHTML = html` 2 处（两个页各一）；
- 一键验收 49 项。

## 我需要改的习惯

加新页签时，我照着自己的「返回 HTML 字符串」写法，但**这个面板的既有约定是函数内部自己写 DOM**。
两种写法混在一起，调用处又不接收返回值 → 必然空白。
以后加页签必须对照既有页的写法，或者统一改造（那是更大的重构，先不动）。

## 你现在要做的

重载到 **0.268** + **Ctrl+F5**。点「守则」「判定」应该正常出内容了。
