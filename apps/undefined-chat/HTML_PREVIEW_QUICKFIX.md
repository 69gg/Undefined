# HTML 预览空白问题 - 快速修复

## 问题定位

HTML 预览窗口打开但显示空白，可能的原因：
1. data URL 太长被截断
2. WebView 加载 data URL 失败
3. CSP 阻止了内容显示

## 快速测试

在浏览器控制台中运行：

```javascript
import { invoke } from '@tauri-apps/api/core';

// 测试简单 HTML
invoke('open_html_preview', {
  input: {
    title: '测试',
    html: '<h1 style="color: red;">Hello World!</h1><p>测试内容</p>'
  }
}).then(() => {
  console.log('预览窗口已打开');
}).catch(err => {
  console.error('预览失败:', err);
});
```

## 可能的解决方案

### 方案 A：使用 App URL 而不是 data URL

修改 `preview.rs`，使用 Tauri 的 asset 协议：

```rust
// 将 HTML 写入临时文件
// 然后使用 tauri://localhost/ 协议加载
```

### 方案 B：简化 HTML 并测试

确保 HTML 不包含任何可能被 CSP 阻止的内容。

### 方案 C：检查终端日志

运行时应该看到：
```
[preview] Creating HTML preview window: html-preview-xxx
[preview] Title: HTML 预览
[preview] HTML size: 123 bytes
[preview] Data URL size: 456 bytes
[preview] Window created successfully: "html-preview-xxx"
```

如果没有这些日志，说明命令根本没被调用。

## 下一步行动

请运行应用并尝试预览 HTML，然后提供：
1. 终端中的所有 `[preview]` 日志
2. 浏览器控制台中的任何错误
3. 预览窗口是否打开（即使是空白）
