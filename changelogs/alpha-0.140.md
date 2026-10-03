# alpha-0.140

## 鸣谢卡结构级等高（0.139 截图仍见错位）

- 0.139 的固定高度仍被内容「撑破」（面板基础样式/内容差异干扰）；
- 本次改为**结构决定形状**：
  - `.thanks-row` 从 flex 改为 **grid 三列**（`repeat(3, 1fr)` 等宽轨道 + 固定行高 120px）——
    卡高卡宽由网格轨道决定，内容差异无法影响；
  - 头像放入**固定 76×76 容器**（overflow hidden + `box-sizing: border-box`），
    图片 100%/100% object-fit cover——无论源图尺寸、白底与否都按容器裁剪；
  - 卡片与内层补齐 box-sizing:border-box，排除 .panel 基础样式干扰；
  - 窄屏自动回单列。
