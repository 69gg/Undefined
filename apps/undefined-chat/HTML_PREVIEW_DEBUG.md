# HTML 预览问题诊断

## 问题
点击"预览 HTML"按钮后，窗口打开但显示空白。

## 已完成的修复
1. ✅ CSP 策略已调整 (允许 data: blob:)
2. ✅ 窗口创建逻辑已改进 (添加回退)
3. ✅ 空内容提示已添加
4. ✅ 调试日志已添加

## 诊断步骤

### 1. 查看终端日志
运行 `npm run tauri:dev` 后，点击"预览 HTML"，查看终端输出：
- 是否有 `[preview] Creating HTML preview window: ...`
- 是否有 `[preview] HTML size: ... bytes`
- 是否有 `[preview] Window created successfully: ...`
- 是否有任何错误信息

### 2. 检查窗口是否创建
- HTML 预览窗口是否成功打开？
- 窗口标题是否显示"HTML 预览"？

### 3. 测试简单 HTML
在聊天中发送这段代码并点击"预览 HTML"：

```html
<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
<h1 style="color: red;">测试</h1>
<p>这是测试内容</p>
</body>
</html>
```

### 4. 可能的原因

#### A. WebView 加载问题
- data URL 可能被 Tauri WebView 阻止
- 需要检查 Tauri 配置中的 webview 设置

#### B. CSP 过于严格
虽然已经放宽，但可能还需要进一步调整。

#### C. 窗口句柄问题
- `main_window` 可能不存在
- 需要回退到第一个可用窗口

## 临时解决方案

### 方案 1：使用 WebView URL 而不是 data URL

修改 `src-tauri/src/preview.rs`：

```rust
// 不使用 data URL，改用自定义协议或文件
// 将 HTML 写入临时文件，然后加载
```

### 方案 2：在主窗口中打开

在 Tauri 配置中允许弹窗，或者在主窗口中创建一个 iframe。

### 方案 3：使用系统浏览器

```rust
// 将 HTML 写入临时文件
// 使用 tauri::api::shell::open() 在浏览器中打开
```

## 下一步

1. 先查看终端日志，确认窗口是否真的创建了
2. 如果窗口创建了但是空白，问题在 data URL 或 CSP
3. 如果窗口没有创建，问题在窗口创建逻辑

## 需要收集的信息

- 终端日志输出
- Tauri 版本
- 操作系统版本
- 是否有任何错误弹窗
