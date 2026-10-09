# AppearancePicker

独立 React 外观选择器，依赖 React 和 @phosphor-icons/react，不依赖 MediaIndex API。

## 复用

复制本目录。在项目全局样式之后导入 `appearance.css`，使用 `useAppearanceTheme()` 获取明暗状态，再渲染：

```tsx
const [theme, setTheme] = useAppearanceTheme();
<AppearancePicker theme={theme} onThemeChange={() => setTheme(theme === "light" ? "dark" : "light")} />
```

默认兼容浏览器键 `mi-theme`、`mi-accent`、`mi-material`，校验未知值，存储不可用时仍支持当前会话，跨标签页同步。模块导入时恢复外观，登录页也能应用已保存的选择。

`accents` 和 `materials` 为预设目录。颜色通过 CSS 变量输出，材质通过 `data-material` 输出；多色搭配只改变装饰色，状态色独立。接入其他项目时给卡片添加 `.appearance-surface`、侧栏添加 `.appearance-sidebar`、内部实色阅读层添加 `.appearance-surface-inner`。MediaIndex 的具体选择器适配独立放在 `src/app/appearance-materials.css`。基础变量与默认配色已包含在样式内。

设计参考（自主 CSS 实现，未引入组件库）：
- https://github.com/hwyuanzi/LiquidGlass-UI
- https://github.com/creativetimofficial/Soft-UI-Dashboard
- https://github.com/shadcn-ui/ui
- https://github.com/radix-ui/themes
- https://github.com/saadeghi/daisyui
- https://github.com/catppuccin/palette
- https://github.com/nordtheme/nord
- https://github.com/radix-ui/colors

当前提供 8 种质感、6 个单色、10 套多色。极光玻璃使用多色透光层，iOS 玻璃使用清透磨砂层，双色渐层使用实色渐变；小卡片和控件共享材质权重。旧 `blocks` 偏好自动映射到缎光瓷面。亮色主按钮文字按相对亮度选择深色或白色。

## Sunny UI 1.0.2 对齐

组件与材质源码同步自 xudong7587/sunny-ui-design-system 的 36793f0（2026-10-09）。保留 GPL-3.0-only 许可；MediaIndex 初始化前缀为 mi，已有偏好无需迁移。共享规范见 SUNNY_UI_STANDARD.md，宿主导航及业务表面适配保留在 app/appearance-materials.css。柔软浮雕采用外凸内凹和独立浅深光影。
