# alpha-0.283

## 移除 set_signature 能力（已迁到认知插件）

`capabilities.set_signature` 与 `capabilities.signature_daily` 移除，
改由认知插件的 `qq_set_signature` 提供。

**注意默认行为变化**：认知那边 `actions.signature_enabled` **默认关**
（签名对外可见，保守）。如果你之前用着陪伴插件这个能力，要去认知的「设置」页打开。
