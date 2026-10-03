# alpha-0.141

## 鸣谢卡改内联布局（照抄记忆插件已验证的方案）

- 记忆插件（用户确认无问题的参照）：人物卡布局全部用**内联 style**（flex:1 1 300px、行 flex 默认
  stretch、头像 76×76 内联、文本 nowrap+ellipsis）——其成功说明内联样式不受外部 CSS
  加载/优先级/缓存干扰；
- storyteller 对齐：`renderThanks` 人物卡改为**全部布局属性内联**（行 flex + 卡 flex:1 1 300px
  min-width:280px + `height:120px` + box-sizing + 头像 76×76 object-fit + 文本单行截断 +
  边框/左高亮线/底色内联），CSS 类只保留**悬停光效**（上浮+光晕，边框增亮用 !important
  压过内联）；三张卡几何完全由内联样式决定——严格同宽同高；
- 顺带确认 AstrBot 插件页静态资源是 `Cache-Control: no-store` 且每次 ?v= 换 URL——
  内联方案进一步杜绝任何资源缓存不确定性。
