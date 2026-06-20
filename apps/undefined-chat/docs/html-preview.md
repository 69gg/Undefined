# HTML 预览

Undefined Chat 处理 HTML 的方式与 WebUI 基线对齐，分为两条互相独立的路径：

- **正文内联渲染**：消息正文里的原始 HTML 通过 `rehype-raw` 解析进 hast 树，再经 `rehype-sanitize` 按白名单清洗后内联渲染（见 `src/rendering/sanitize.ts`）。该路径**绝不执行脚本**——`script`、`on*` 事件属性、`style` 属性会被剥离，协议限制为 `http/https/mailto` 等安全协议，并以 `hast-util-sanitize` 的 `defaultSchema` 为安全基线，仅最小化放开 `className` 等纯展示属性。
- **独立预览窗口**：HTML/HTM 代码块右上角显示“预览 HTML”。预览由 Tauri Rust command 创建独立 WebView 窗口或 Android Activity，主 React 应用只负责传入 `{ title, html }`。**预览窗口内可运行脚本**（详见下文 CSP）。

下文主要描述独立预览窗口路径。

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

当前 CSP（见 `src-tauri/src/preview.rs` 的 `PREVIEW_CSP`）：

```text
default-src 'none';
connect-src 'none';
form-action 'none';
object-src 'none';
base-uri 'none';
frame-ancestors 'none';
img-src data: blob:;
media-src data: blob:;
style-src 'unsafe-inline';
font-src data:;
script-src 'unsafe-inline';
```

这意味着：

- **允许内联脚本（`script-src 'unsafe-inline'`）**：与 WebUI HTML 预览基线对齐，放开内联脚本以支持图表/动画等工具产物。不放开 `unsafe-eval`。
- 允许内联 CSS。
- 图片和媒体只允许 `data:` / `blob:`。
- `connect-src 'none'` 禁止一切外联请求，防止脚本把内容外泄。
- 禁止表单提交（`form-action 'none'`）、插件对象（`object-src 'none'`）和 `base` 改写（`base-uri 'none'`）。
- 预览是隔离容器，不是 HTML 净化器；传入内容会按原样渲染。

### 放开脚本后如何维持隔离

放开 `script-src` 意味着预览窗口可执行任意脚本，但其无法访问 Tauri IPC/invoke，也无法外联或导航出去。多重边界共同生效：

- **IPC 隔离靠 capability 缺失（而非 `withGlobalTauri`）**：预览窗口 label 形如 `html-preview-{uuid}`，不匹配 `capabilities/default.json`（`main-capability`，仅授权 `windows: ["main"]`）。Tauri v2 ACL 模型下，未匹配任何 capability 的 webview 完全没有 IPC 访问权，因此即便脚本被放开，也无法回调 Rust 命令或读取主窗口数据。底层 `__TAURI_INTERNALS__` 无论 `withGlobalTauri` 取值都会注入，故隔离不能寄托于此；`preview.rs` 的 `test_preview_window_has_no_ipc_capability` 会在有人误把 capability 放宽到 `*` 或 `html-preview-*` 时失败。
- **外联阻断**：`connect-src 'none'` 切断脚本的网络出口。
- **导航防护不靠 CSP**：由 Rust 侧 `on_navigation` 守卫（`preview_navigation_allowed`）只允许初始 URL 和 `about:blank`。
- **防嵌入靠窗口隔离**：预览是独立 OS 窗口而非 iframe，配合 `on_new_window` Deny 覆盖。`frame-ancestors 'none'` 通过 `<meta http-equiv>` 交付时被浏览器忽略（仅 HTTP 响应头有效），保留该指令仅为未来改用 header 交付时即可生效。
- 曾用的 `navigate-to 'none'` 已移除——该指令已从 CSP 规范删除、浏览器从不实现，是零防护的死指令。

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
- 可运行内联脚本（`script-src 'unsafe-inline'`），但不放开 `unsafe-eval`。
- 不加载外部 CSS、图片、字体或网络资源（`connect-src 'none'`）。
- 不支持表单提交和 iframe 外部嵌入。
- 临时文件位于系统 temp 目录，关闭窗口和下次打开前会清理 `html-preview-*.html`。

## 测试

```bash
cd apps/undefined-chat
npm run test:unit -- src/rendering/HtmlPreview.test.tsx src/rendering/CodeBlock.test.tsx
npm run tauri:test
```

Rust 测试覆盖：

- CSP 策略：放开内联脚本但禁止 `unsafe-eval`，保留 `default-src`/`connect-src`/`form-action`/`object-src`/`base-uri` 隔离指令，且不含已移除的 `navigate-to`。
- IPC 隔离回归：预览窗口 label 不被任何 capability 的 `windows` 作用域命中（防止误放宽到 `*` / `html-preview-*`）。
- 标题转义。
- 1 MB 限制。
- 初始 URL/`about:blank` 导航守卫。
- 临时文件识别和残留清理 helper。

真实 Tauri smoke 仍需要覆盖窗口打开、关闭清理、Windows/空格/非 ASCII 路径和 Android Activity。
