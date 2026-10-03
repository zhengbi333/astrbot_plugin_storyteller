# alpha-0.219

## 25 模块深度自检 · 第 5 轮：appearance 外观

### 发现的问题：后端默认主题在前端根本不存在

| | |
|---|---|
| 前端 `THEMES` | `tide / aurora / pearl / nebula / deepsea / fern / rose / onyx`（潮汐·极光·月白·星云·深海·幽谷·春霞·玄墨） |
| 后端 `DEFAULTS["theme"]` | **`"cosmic"`** ← 不存在 |

**症状**：新用户，或点过「恢复」重置外观之后 —— `themeVars("cosmic")` 找不到主题，
页面**只剩明/暗基础色、没有主题配色**；而外观页的主题名却兜底显示"潮汐"，**显示与实际不一致**。
（`themeVars` 本身有兜底不会崩，所以表现为"配色丢失"而不是报错，很容易被忽略。）

### 修复

1. **后端**：默认值改为 `tide`，并新增 `_KNOWN_THEMES`（8 套白名单）；`_normalize()` 里主题不在白名单一律回落 `tide`
   → **用户配置里已存的脏值（包括旧的 `cosmic`）下次读取即自愈**
2. **前端**：`themeVars()` 兜底从"只剩基础色"改为"回落 tide"（第二道防线）

### 实测 23/23 通过

| 项目 | 结果 |
|---|---|
| 自愈 | `cosmic / "" / not-a-theme / onnx` → `tide`；`aurora`、`"  pearl  "` → 原样保留 |
| scheme 校验 | dark/light/auto 合法；`weird`、`""` → `auto` |
| 数值 clamp | 透明度 5→1.0、-3→0.0；模糊 999→60、-5→0 |
| 字段白名单 | `evil_field`、`__proto__` 不进入状态 |
| 图库 | 写入侧 `_BG_LIBRARY_LIMIT=5`；扩展名白名单；缩略图 `_THUMB_SIZE=120` |
| 前后端一致 | 8 套主题逐一比对通过 |

**截图目视**：`_st_test/preview/audit5-appearance.png`（8 套主题色块、明暗三档、自定义色、背景板滑块都正常）
