# HTML 预览空白问题修复

## 问题描述
点击"预览 HTML"按钮后，弹出的窗口显示空白，无法看到 HTML 内容。

## 根本原因分析
1. **CSP 策略过于严格**：原始的 CSP 设置 `default-src 'none'` 阻止了所有默认内容加载
2. **主窗口获取失败**：硬编码的 "main" 标签可能与实际窗口标签不匹配
3. **空内容无反馈**：当 HTML 为空或加载失败时，用户看不到任何提示

## 修复方案

### 1. 放宽 CSP 策略 (preview.rs:8-19)
```rust
const PREVIEW_CSP: &str = concat!(
    "default-src 'self' data: blob:; ",    // 允许 data: 和 blob: URL
    "connect-src 'none'; ",
    "form-action 'none'; ",
    "object-src 'none'; ",
    "base-uri 'self'; ",                   // 允许 'self' 作为基础 URI
    "frame-ancestors 'none'; ",
    "img-src data: blob: 'self'; ",        // 允许图片加载
    "media-src data: blob: 'self'; ",      // 允许媒体加载
    "style-src 'unsafe-inline' 'self'; ",  // 允许内联样式和 'self'
    "font-src data: 'self'; ",             // 允许字体加载
    "script-src 'none'"                    // 保持脚本禁用（安全）
);
```

**安全性说明**：
- ✅ 仍然禁用脚本执行 (`script-src 'none'`)
- ✅ 阻止网络连接 (`connect-src 'none'`)
- ✅ 阻止表单提交 (`form-action 'none'`)
- ✅ 阻止导航到外部 URL (`on_navigation` 钩子)
- ✅ 仅允许必要的资源类型加载

### 2. 改进窗口创建逻辑 (preview.rs:74-100)
```rust
// 尝试多种方式获取父窗口
let main_window = app
    .get_webview_window("main")
    .or_else(|| app.webview_windows().into_values().next())
    .ok_or_else(|| "no parent window is available for html preview".to_string())?;
```

**改进点**：
- 首先尝试获取 "main" 标签的窗口
- 如果失败，回退到第一个可用窗口
- 添加详细的调试日志（eprintln）

### 3. 添加空内容提示 (preview.rs:35-52)
```rust
pub(crate) fn preview_document(title: &str, html: &str) -> String {
    // ... 省略部分代码
    format!(
        // ... HTML 结构
        "<style>",
        "body {{ margin: 0; padding: 16px; /* ... */ }}",
        "body.empty {{ display: flex; align-items: center; justify-content: center; }}",
        "body.empty::before {{ content: '内容为空或加载失败'; color: #999; }}",
        "</style>",
        // ...
        if html.trim().is_empty() { "empty" } else { "" },
        html
    )
}
```

**改进点**：
- 当 HTML 内容为空或仅包含空白字符时，显示友好提示
- 添加基础样式，确保视觉反馈
- 保持内容居中对齐

### 4. 添加调试日志 (preview.rs:86-89)
```rust
eprintln!("[preview] Creating HTML preview window: ", label);
eprintln!("[preview] Title: {}", input.title);
eprintln!("[preview] HTML size: {} bytes", input.html.len());
eprintln!("[preview] Data URL size: {} bytes", url.as_str().len());
```

## 测试方法

### 方法 1: 使用测试 HTML 文件
提供了一个完整的测试文件 `test_html_preview.html`，包含以下测试场景：
- ✅ 基本文本渲染
- ✅ CSS 样式支持
- ✅ SVG 图片（Data URL）
- ✅ 列表和表格
- ✅ 内联样式

### 方法 2: 通过聊天界面测试
1. 启动应用：`npm run tauri:dev`
2. 在聊天中发送以下消息：
```
请生成一个简单的 HTML 页面，包含标题和段落
```
3. 当 AI 返回 HTML 代码块时，点击"预览 HTML"按钮
4. 验证弹出窗口正确显示内容

### 方法 3: 手动测试简单 HTML
在聊天中输入：
```
\`\`\`html
<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
  <h1 style="color: blue;">Hello World</h1>
  <p>如果你能看到这段文字，说明预览功能正常！</p>
</body>
</html>
\`\`\`
```

### 方法 4: 测试空内容
```
\`\`\`html

\`\`\`
```
应该看到"内容为空或加载失败"的提示。

## 单元测试验证
```bash
cd src-tauri
cargo test --lib preview::tests
```

所有 19 个测试应该通过，包括新增的：
- `test_preview_document_empty_content`
- `test_preview_document_whitespace_only`
- `test_preview_document_non_empty_content`

## 查看调试日志
在开发模式下运行时，终端会输出预览相关的日志：
```
[preview] Creating HTML preview window: html-preview-12345678-...
[preview] Title: HTML 预览
[preview] HTML size: 234 bytes
[preview] Data URL size: 567 bytes
[preview] Window created successfully: "html-preview-..."
```

如果窗口创建失败，会输出详细的错误信息。

## 后续改进建议
1. **错误处理增强**：在前端显示更友好的错误提示
2. **主题支持**：根据系统主题自动切换预览窗口的亮/暗色模式
3. **内容验证**：在前端提前验证 HTML 大小，避免超过 1MB 限制
4. **预览历史**：允许用户查看最近预览过的 HTML
5. **导出功能**：允许将预览的 HTML 保存为文件

## 安全注意事项
虽然已经放宽了 CSP 策略，但仍然保持了关键的安全限制：
- ❌ 脚本执行被完全禁用
- ❌ 无法发起网络连接
- ❌ 无法提交表单
- ❌ 无法导航到外部 URL
- ✅ 仅支持渲染静态 HTML 内容

这些限制确保了即使恶意 HTML 也无法执行危险操作。
