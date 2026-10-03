# alpha-0.149

## 生图修复轮（用户实测反馈：硅基流动 Z-Image-Turbo）

### 🔴 主 bug：端点配置键名不一致 → 「独立 API 未配置完整」永远误报

- 根因：`_endpoints()` / `_missing_fields()` 读取的键是 `image.base_url` / `image.api_key` / `image.model`，而前端字段与 schema 键是 **`image.api_base_url` / `image.api_api_key` / `image.api_model`**（主端点键少了 `api_` 前缀）——**前端填得多完整，后端也永远读到空** → 报「未配置完整」；备端点键名反而正确。
- 修复：端点键映射与 schema 完全一致（`_ENDPOINT_KEYS` 显式列出主/备各 4 键），补齐读取；「未配置完整」错误改为**点名缺哪项**（如「主端点还差：API Key」），生图页状态行同步显示。

### 🔴 副 bug：base 已含 /v1 时拼出双 /v1 → 404

- `https://api.siliconflow.cn/v1` + `/v1/images/generations` = **`/v1/v1/images/generations`**（必 404）；已修复为检测 `/v1` 结尾只补 `/images/generations`（seedream/minimax 同理）。

### 兼容增强（通用自适应，非平台特配）

- 部分平台尺寸参数名为 `image_size` 而非 `size`：400 且报错含 size 时自动用 `image_size` 重试一次。

### ✅ 真机实测（用户提供 key，临时环境变量传入，不落盘不残留）

- `https://api.siliconflow.cn/v1` + `Tongyi-MAI/Z-Image-Turbo` + prompt「一片森林」：端点归一化 `/v1/images/generations` → 生成成功 **5.4s** → PNG 2.2MB 魔数校验通过 → 落盘/解析全链路正常（样图见 dev/smoke/_img_output/forest_test.png，1024×1024）。

### 回归

- smoke_image_intent **22 项**（+5 端点读取/点名断言）；verify_interact 44 / verify_057 169 / verify_046 31 / **40 项冒烟 0 失败**；key 未写入任何文件（环境变量方式，测试后清理）。