# HTML 预览功能

## 功能概述

undefined-chat 支持在对话中直接预览 AI 生成的 HTML 代码，提供跨平台的安全预览体验。

## 功能特性

### 1. 自动识别 HTML 代码块

当 AI 回复包含 HTML 或 HTM 代码块时，会自动在代码块右上角显示"预览 HTML"按钮：

````markdown
```html
<!DOCTYPE html>
<html>
<head>
    <title>示例页面</title>
</head>
<body>
    <h1>Hello World</h1>
</body>
</html>
```
````

### 2. 跨平台支持

#### 桌面端 (Windows / macOS / Linux)
- 点击"预览 HTML"按钮，在新的独立窗口中打开预览
- 窗口尺寸：900x700 像素（可调整大小）
- 支持多个预览窗口同时打开

#### 移动端 (Android)
- 点击"预览 HTML"按钮，在新的 Activity 中打开预览
- 使用原生 Android WebView 渲染
- 支持全屏显示和手势操作

### 3. 安全防护

#### Content Security Policy (CSP)
预览窗口注入严格的 CSP 头，限制以下行为：

```
default-src 'none';          # 默认拒绝所有资源
connect-src 'none';          # 禁止网络连接
form-action 'none';          # 禁止表单提交
object-src 'none';           # 禁止插件
script-src 'none';           # 禁止 JavaScript 执行
navigate-to 'none';          # 禁止导航
img-src data: blob:;         # 仅允许 data: 和 blob: 图片
media-src data: blob:;       # 仅允许 data: 和 blob: 媒体
style-src 'unsafe-inline';   # 允许内联样式
```

#### 导航限制
- 仅允许访问初始 data: URL 和 about:blank
- 阻止所有外部链接跳转
- 阻止打开新窗口

#### 大小限制
- 单次预览 HTML 内容限制：1 MB
- 超过限制会拒绝预览并提示错误

#### 标题转义
- 窗口标题自动 HTML 转义，防止注入攻击
- 内容本身不转义，保持原样渲染（依赖 CSP 隔离）

## 技术实现

### 前端架构

```
MarkdownContent.tsx
  ├─ 检测 HTML/HTM 代码块
  ├─ 渲染"预览 HTML"按钮
  └─ 调用 onPreviewHtml({ title, html })
       ↓
App.tsx
  └─ 调用 client.openHtmlPreview({ title, html })
       ↓
runtime-client/tauri.ts
  └─ invoke("open_html_preview", { input })
       ↓
Tauri Rust Backend
```

### Rust 后端实现

**文件**: `src-tauri/src/preview.rs`

#### 核心函数

1. **`build_preview_data_url`**
   - 构建 data: URL，包含完整的 HTML 文档
   - 注入 CSP meta 标签
   - URL 编码内容

2. **`preview_document`**
   - 生成完整的 HTML 文档结构
   - 注入 CSP、viewport、charset

3. **`escape_html_text`**
   - 转义窗口标题中的 HTML 字符
   - 防止 XSS 注入

4. **`preview_navigation_allowed`**
   - 导航守卫，仅允许初始 URL 和 about:blank

5. **`open_html_preview`** (Tauri command)
   - 创建新的 WebView 窗口
   - 桌面端：独立窗口
   - Android：指定 Activity

### Android 集成

**准备脚本**: `scripts/prepare_tauri_android.py`

自动化流程：
1. 检测 `package.json` 中的 `app.name` 是否为 `undefined-chat`
2. 生成 `HtmlPreviewActivity.kt`：
   ```kotlin
   package com.undefined.chat
   
   class HtmlPreviewActivity : TauriActivity()
   ```
3. 在 `AndroidManifest.xml` 中注册 Activity：
   ```xml
   <activity
       android:name="com.undefined.chat.HtmlPreviewActivity"
       android:exported="false" />
   ```

**运行准备脚本**:
```bash
npm run tauri:android:prepare
```

**检查状态**:
```bash
npm run tauri:android:prepare:check
```

## 使用场景

### 1. 静态页面预览
适合预览纯 HTML + CSS 的静态页面：
- 个人简历
- 宣传页面
- 文档页面

### 2. 数据可视化
使用内联 SVG 或 Canvas（需要内联 data: 图片）：
- 图表
- 图形
- 动画效果

### 3. 样式演示
展示 CSS 效果：
- 布局示例
- 组件样式
- 响应式设计

## 限制与约束

### 不支持的功能

1. **JavaScript 执行**
   - CSP 禁止所有 JavaScript
   - 无法运行交互式脚本

2. **外部资源加载**
   - 无法加载外部 CSS、图片、字体
   - 仅支持 data: URL 和 blob: URL

3. **网络请求**
   - 无法发起 fetch、XMLHttpRequest
   - 无法连接 WebSocket

4. **表单提交**
   - 禁止表单提交
   - 仅供展示用途

5. **插件和对象**
   - 禁止 Flash、PDF 嵌入等

### 大小限制

- 单次预览内容：1 MB (包含标题和 HTML)
- 建议控制在 100 KB 以内以获得最佳体验

## 测试覆盖

### 前端测试 (Vitest)

**文件**: `src/rendering/HtmlPreview.test.tsx`

测试用例：
- 检测 HTML/HTM 代码块显示预览按钮
- 非 HTML 代码块不显示按钮
- 点击按钮触发正确的回调
- 正确传递标题和 HTML 内容
- 多代码块独立处理

### Rust 测试 (cargo test)

**文件**: `src-tauri/src/preview.rs`（嵌入式测试模块）

测试用例：
- HTML 文本转义
- 文档结构生成
- CSP 注入
- 导航守卫
- 大小限制
- URL 编码
- 安全策略验证

**运行测试**:
```bash
cd apps/undefined-chat
npm run test                    # 前端测试
cargo test --lib preview        # Rust 测试
```

## 故障排查

### 桌面端问题

**问题**: 点击按钮无反应
- **检查**: 主窗口是否正常运行
- **解决**: 确保 Tauri 应用正常启动

**问题**: 窗口创建失败
- **检查**: 控制台错误日志
- **解决**: 检查 HTML 内容大小是否超限

### Android 问题

**问题**: 预览无法打开
- **检查**: 是否运行了 `npm run tauri:android:prepare`
- **检查**: `AndroidManifest.xml` 中是否包含 `HtmlPreviewActivity`
- **解决**: 重新运行准备脚本并重新编译

**问题**: Activity 未声明错误
- **解决**: 
  ```bash
  npm run tauri:android:prepare
  npm run tauri:android
  ```

### 内容显示问题

**问题**: 样式不生效
- **原因**: 外部 CSS 被 CSP 阻止
- **解决**: 使用内联样式 `<style>...</style>`

**问题**: 图片不显示
- **原因**: 外部图片 URL 被 CSP 阻止
- **解决**: 使用 data: URL `<img src="data:image/png;base64,..."/>`

**问题**: 脚本不执行
- **原因**: CSP 禁止 JavaScript（设计如此）
- **解决**: 使用纯 HTML + CSS 实现效果

## 安全注意事项

### 对用户
- 预览的 HTML 来自 AI 模型，虽然有 CSP 保护，但仍建议谨慎预览未知来源的代码
- 如发现可疑内容，请关闭预览窗口

### 对开发者
- 预览功能是**隔离容器**，不是**内容净化器**
- 依赖 CSP 和导航守卫提供安全边界
- 不要修改 CSP 策略以"修复"某些功能，这会引入安全风险
- 如需扩展功能，优先考虑提供独立的"导出 HTML"功能

## 未来扩展

可能的增强方向：

1. **导出功能**: 将预览的 HTML 保存为独立文件
2. **截图功能**: 捕获预览窗口为图片
3. **打印功能**: 直接打印预览内容
4. **模板库**: 提供常用 HTML 模板供 AI 参考
5. **实时编辑**: 支持在预览中直接修改并同步到对话

## 相关文件

- 前端渲染: `src/rendering/MarkdownContent.tsx`
- 前端测试: `src/rendering/HtmlPreview.test.tsx`
- Rust 后端: `src-tauri/src/preview.rs`
- Android 准备: `scripts/prepare_tauri_android.py`
- 类型定义: `src/runtime-client/types.ts`

## 参考资料

- [Tauri WebView Window API](https://tauri.app/reference/javascript/api/namespacewebviewwindow/)
- [Content Security Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP)
- [Data URLs](https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/Data_URLs)
