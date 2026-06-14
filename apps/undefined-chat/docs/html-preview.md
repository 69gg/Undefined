# HTML 预览

Undefined Chat 支持在 HTML/HTM 代码块右上角显示“预览 HTML”。预览由 Tauri Rust command 创建独立 WebView 窗口或 Android Activity，主 React 应用只负责传入 `{ title, html }`。

## 运行路径

```text
MarkdownContent / CodeBlock
  -> onPreviewHtml({ title, html })
  -> runtime-client/tauri.openHtmlPreview
  -> invoke("open_html_preview")
  -> src-tauri/src/preview.rs
```

Rust 侧流程：

1. `preview_document_checked` 校验标题 + HTML 总长度不超过 1 MB。
2. 生成带 CSP meta 的完整 HTML 文档。
3. 写入系统临时目录下的 `html-preview-*.html`。
4. 用 `Url::from_file_path` 生成初始 `file://` URL。
5. 创建独立预览窗口；Android 指定 `HtmlPreviewActivity`。
6. 导航守卫只允许初始 URL 和 `about:blank`。
7. 窗口 close/destroy 时删除对应临时文件；每次打开前也会清理旧的 `html-preview-*.html` 残留。

`build_preview_data_url` 仍保留为测试/未来回退 helper，但不是当前运行路径。

## CSP

当前 CSP：

```text
default-src 'none';
connect-src 'none';
form-action 'none';
object-src 'none';
base-uri 'none';
frame-ancestors 'none';
navigate-to 'none';
img-src data: blob:;
media-src data: blob:;
style-src 'unsafe-inline';
font-src data:;
script-src 'none';
```

这意味着：

- 禁止 JavaScript、`unsafe-eval`、网络请求、表单提交、插件对象和外部导航。
- 允许内联 CSS。
- 图片和媒体只允许 `data:` / `blob:`。
- 预览是隔离容器，不是 HTML 净化器；传入内容会按原样渲染。

## Android

`npm run tauri:android:init` 会在生成 Android 工程后运行 `scripts/prepare_tauri_android.py`，注册 `HtmlPreviewActivity`：

```kotlin
package com.undefined.chat

class HtmlPreviewActivity : TauriActivity()
```

验证命令：

```bash
npm run tauri:android:prepare:check
npm run tauri:android:debug -- --apk
```

真实设备需要确认 Activity 能打开、返回后主窗口仍可用，并且预览窗口不能导航到外部站点。

## 限制

- 单次预览标题 + HTML 最大 1 MB。
- 不执行 JavaScript。
- 不加载外部 CSS、图片、字体或网络资源。
- 不支持表单提交和 iframe 外部嵌入。
- 临时文件位于系统 temp 目录，关闭窗口和下次打开前会清理 `html-preview-*.html`。

## 测试

```bash
cd apps/undefined-chat
npm run test:unit -- src/rendering/HtmlPreview.test.tsx src/rendering/CodeBlock.test.tsx
npm run tauri:test
```

Rust 测试覆盖：

- CSP 策略。
- 标题转义。
- 1 MB 限制。
- 初始 URL/`about:blank` 导航守卫。
- Windows/空格/非 ASCII 路径通过 `Url::from_file_path` 的构造路径。
- 临时文件识别和残留清理 helper。

真实 Tauri smoke 仍需要覆盖窗口打开、关闭清理和 Android Activity。
