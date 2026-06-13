# 测试修复进度

## 问题概览

**失败测试总数**：19 个
- 单元测试：4 个
- E2E 测试：15 个

---

## 单元测试失败（4个）

### 1. src/App.test.tsx
**测试**：`uses native attachment bridges for timeline actions`
**错误**：找不到 "report.png" 文本
**原因**：AttachmentCard 渲染逻辑变化
**状态**：🔄 修复中

### 2. src/image-viewer/ImageViewerModal.test.tsx
**测试**：`点击关闭按钮应该关闭查看器`
**错误**：关闭按钮点击未触发 onClose
**原因**：事件处理或选择器问题
**状态**：🔄 修复中

### 3-4. src/platform/ConnectionSetup.test.tsx
**测试 1**：`validates URL format`
**测试 2**：`requires both URL and API key`
**错误**：表单验证断言失败
**原因**：验证逻辑未实现或测试断言不正确
**状态**：🔄 修复中

---

## E2E 测试失败（15个）

### tests/e2e/attachment-upload.test.tsx (3个)
- 显示上传错误
- 移除附件
- 阻止发送包含上传失败附件的消息

**共同问题**：
- Tauri 文件选择器 Mock 不完整
- 附件状态更新未正确触发

**状态**：🔄 修复中

### tests/e2e/command-execution.test.tsx (5个)
- 使用键盘导航命令列表
- 选择命令后填充到输入框
- Enter 键选择当前高亮的命令
- Escape 键关闭命令面板
- 发送命令消息

**共同问题**：
- 命令面板 DOM 查询不匹配
- 键盘事件 Mock 需要完善
- 命令数据 Mock 不完整

**状态**：🔄 修复中

### tests/e2e/connection-setup.test.tsx (2个)
- 已有配置时可以通过设置按钮重新打开配置面板
- 配置面板中 API Key 输入框对已有配置显示占位符

**共同问题**：
- 配置存储 Mock 不完整
- 设置按钮查询选择器问题

**状态**：🔄 修复中

### tests/e2e/conversation-management.test.tsx (2个)
- 显示会话列表中的消息计数
- 高亮当前选中的会话

**共同问题**：
- 会话元数据 Mock 缺失
- CSS 类名不匹配

**状态**：🔄 修复中

### tests/e2e/history-loading.test.tsx (2个)
- 支持分页加载更多历史
- 显示消息角色（用户/机器人）

**共同问题**：
- 历史分页 API Mock 不完整
- 滚动事件触发问题

**状态**：🔄 修复中

### tests/e2e/message-sending.test.tsx (1个)
- 支持换行输入（Shift+Enter）

**共同问题**：
- Shift+Enter 事件模拟问题
- userEvent.keyboard 使用不正确

**状态**：🔄 修复中

---

## 修复策略

### 阶段 1：单元测试修复
1. 修复 App.test.tsx 的附件渲染断言
2. 修复 ImageViewer 关闭按钮逻辑
3. 完善 ConnectionSetup 表单验证

### 阶段 2：E2E Mock 完善
1. 完善 test-fixtures.ts 中的所有 Mock
2. 更新查询选择器（优先使用 data-testid）
3. 增加异步等待时间
4. 修复键盘事件模拟

---

## 预期结果

修复后：
- ✅ 单元测试：100% 通过
- ✅ E2E 测试：目标 90%+ 通过（部分复杂场景可能仍需调整）
- ✅ 核心功能：保持 100% 测试覆盖

---

## 执行状态

**开始时间**：2026-06-13 13:00  
**预计完成**：20-30 分钟  
**当前状态**：🔄 Workflow 运行中

使用 `/workflows` 查看实时进度。
