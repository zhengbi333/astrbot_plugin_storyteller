# alpha-0.281

## 两个 SnowLuma 动作：改签名 + 名片赞

都是「她作为一个人会做的小动作」，所以放**陪伴插件的 capabilities**
（和 `poke` / `photo_take` 同级），不进认知插件。

### 1. `set_signature` — 改个性签名

```
SnowLuma: set_self_longnick  { long_nick: "文本" }
工具名:   story_set_signature
```

- **必须用 `long_nick` 这个参数名**（SnowLuma 的参数是严格 string）；
- **60 字上限**：超了直接拒绝并让模型改短，不硬塞；
- **默认日限 2 次** —— 签名**对外可见**，改太勤像营销号；
- 说明里明确写了「不要每次聊天都改」。

### 2. `like_contact` — 名片赞

```
SnowLuma: send_like  { user_id, times }
工具名:   story_like_contact
```

- `user_id` 从事件取（不让模型猜 QQ 号）；
- `times` 夹在 **1~5**（模型填 99 也只会点 5 次）；
- **默认日限 5 次** —— 真人不会一天点十几次；
- 说明里写了「这个动作很轻，通常不用专门说出来」。

## 面板可见（你要求的）

| 配置项 | 默认 | 面板位置 |
|---|---|---|
| `capabilities.signature_daily` | **2** | 设置 → 能力 |
| `capabilities.like_daily` | **5** | 设置 → 能力 |
| `capabilities.poke_daily` | **10** | 设置 → 能力（0.280 已加） |

三项都带 hint，说明「为什么是这个数」「0 = 不限制（不建议）」。

## 验证（`audit_97_signature_like.py` 35/35）

- **A** 两个能力都在表里、日限键正确、说明含「用/不要用」；
- **B** 签名：调 `set_self_longnick`、参数名是 **`long_nick`**（不是 text）、文本传对；
- **C** 签名边界：空文本拒、超长拒、平台不支持明说；
- **D** 点赞：调 `send_like`、`user_id` 是 int、`times` 传对；
- **E** **次数夹紧实测**：`0→1 / 1→1 / 3→3 / 99→5 / -5→1 / "abc"→1` 六种全对；
- **F** 失败如实告知（`ok=False` + "如实说没点上"）、拿不到 QQ 号时拒绝；
- **G** 三个配置项都在 schema、默认值正确、都有 hint。

## 已知边界

- 只做了「她主动改签名 / 点赞」，**没做"什么时候该改"的触发策略** —— 现在是模型看到工具后自己判断；
- 签名改完是**真对外可见**的，日限 2 次是我保守设的，你觉得可以更多就改配置；
- `send_like` 在部分账号上可能有频率限制（QQ 侧），失败会如实返回。
