# alpha-0.261

## 一、judge.py 升级：每个判定绑自己的模型

判定器不再"统一用一个模型"，而是**按模块绑定**，并带三级回退：

```
① 自己的配置键（image.judge_provider_id / search.provider_id / emotion.provider_id …）
② 统一判定模型（judge.provider_id）
③ 当前对话模型
```

新增 `resolve_provider(plugin)`，判定器自己会找模型，调用方不用管。

## 二、判定器从 4 个扩到 7 个

| 判定器 | 绑的配置键 | 候选 |
|---|---|---|
| `image_kind` | `image.judge_provider_id` | 画图 / 文档 / 其他 |
| `search_need` | `search.provider_id` | 要查 / 不用 |
| `emotion_event` | `emotion.provider_id` | 八类情绪事件 |
| `recall_need` | `recall.provider_id` | 要撤回 / 不用 |
| **`promise_settle`** | `promise.provider_id` | 兑现了 / 没兑现 |
| **`memory_dup`** | `memory.profile_provider_id` | 重复 / 不重复 |
| **`emoji_pref`** | `emoji.judge_provider_id` | 少发 / 多发 / 无关 |

后三个是新增的 —— 它们原来分别靠"二元组相似度"和"关键词"，都属于 R6 要整改的对象。

## 三、配置补齐

- 新增 `judge` 组：`provider_id`（统一判定模型）、`daily_limit`（每类日限 300）、`timeout`（6 秒）；
- `recall` 组补 `provider_id`；
- 新增 `promise` 组：`provider_id`；
- 全部带中文说明 + hint，面板「设置」里可直接改。

## 四、生图判定改用判定器自己的模型

原来是 `self._judge_provider()`（只看 `judge.provider_id`），现在改成
`judge_mod.IMAGE_KIND.resolve_provider(self)` —— 优先用 `image.judge_provider_id`。

## 五、验证

- 7 个判定器全部绑定成功（provider_key 逐项核对）；
- schema 类型全部合法（0 问题）；
- 生图判定接线已确认。

## 六、用户配置建议（空着的 5 个）

| 配置项 | 建议值 |
|---|---|
| `emotion.provider_id` | `deepseek/deepseek-v4-flash-vision-exp` |
| `image.judge_provider_id` | 同上 |
| `relationship.provider_id` | 同上 |
| `silence.provider_id` | 同上 |
| `judge.provider_id` | 同上（统一兜底） |

不填也能跑（会回退到当前对话模型），但填了以后每个判定的费用能单独看。

## 七、待整改（下一轮）

搜索意图、情绪事件、撤回、约定结算、记忆去重、表情偏好这 6 处的**调用点**
还没换成 judge —— 判定器建好了，但业务代码仍在用旧的关键词/相似度。
