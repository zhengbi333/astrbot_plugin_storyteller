# alpha-0.282

## 移除 poke 能力（已迁到认知插件）

按"认知插件 = 统一工具库"的原则，`capabilities.poke` 与 `capabilities.poke_daily`
从本插件移除，改由认知插件的 `qq_poke` 工具提供。

**行为不变**：模型仍然可以"戳一戳"，只是注册位置换了，而且现在**有权限门**（访客不能用）。

## 还没迁的

`set_signature`（改签名）和 `like_contact`（名片赞）仍在 `capabilities` 里，
按计划逐个迁到认知插件后再删。
