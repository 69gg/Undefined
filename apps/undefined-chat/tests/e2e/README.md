# E2E 测试套件

本目录包含 undefined-chat 的端到端集成测试，验证完整的用户交互流程。

## 测试文件结构

```
tests/e2e/
├── connection-setup.test.tsx       # 连接配置流程
├── conversation-management.test.tsx # 会话创建/切换/删除
├── message-sending.test.tsx        # 发送消息和接收回复
├── attachment-upload.test.tsx      # 附件上传流程
├── command-execution.test.tsx      # 命令面板使用
└── history-loading.test.tsx        # 历史分页加载
```

## 运行测试

```bash
# 运行所有 E2E 测试
npm run test:e2e

# 监听模式运行 E2E 测试
npm run test:e2e:watch

# 运行单元测试
npm run test:unit

# 运行所有测试（单元 + E2E）
npm run test:all

# 运行单个测试文件
npm run test:e2e -- connection-setup.test.tsx
```

## 测试覆盖范围

### connection-setup.test.tsx
- ✅ 显示连接配置界面
- ✅ 保存配置并引导应用
- ✅ 表单验证（URL 和 API Key 必填）
- ✅ 不安全存储降级选项
- ✅ 配置保存错误处理
- ✅ 已有配置时重新打开设置面板

### conversation-management.test.tsx
- ✅ 创建新会话
- ✅ 在不同会话间切换
- ✅ 显示会话列表中的消息计数
- ✅ 高亮当前选中的会话
- ✅ 移动端视口自动关闭侧边栏
- ✅ 默认选中第一个会话

### message-sending.test.tsx
- ✅ 发送文本消息并接收回复
- ✅ 阻止在 job 运行时发送消息
- ✅ 阻止发送空消息
- ✅ 支持换行输入（Shift+Enter）
- ✅ Enter 键发送消息
- ✅ 显示发送错误
- ✅ 草稿在会话间独立保存
- ✅ 发送后清空草稿和附件

### attachment-upload.test.tsx
- ✅ 通过原生文件选择器添加附件
- ✅ 显示上传中状态
- ✅ 显示上传错误
- ✅ 移除附件
- ✅ 阻止在附件上传中时发送消息
- ✅ 阻止发送包含上传失败附件的消息
- ✅ 发送消息时包含附件 ID
- ✅ 用户取消文件选择时不触发上传
- ✅ 附件在发送后被清空

### command-execution.test.tsx
- ✅ 通过斜杠快捷键打开命令面板
- ✅ 过滤命令列表
- ✅ 使用键盘导航命令列表
- ✅ 选择命令后填充到输入框
- ✅ Enter 键选择当前高亮的命令
- ✅ Escape 键关闭命令面板
- ✅ 删除斜杠后关闭命令面板
- ✅ 没有匹配的命令时显示空状态
- ✅ 发送命令消息

### history-loading.test.tsx
- ✅ 初始加载会话历史
- ✅ 按时间顺序显示消息
- ✅ 支持分页加载更多历史
- ✅ 没有更多历史时隐藏加载按钮
- ✅ 空会话显示空状态
- ✅ 切换会话时缓存历史
- ✅ 显示历史加载错误
- ✅ 显示消息角色（用户/机器人）

## 测试技术栈

- **Vitest**: 测试框架
- **@testing-library/react**: React 组件测试
- **@testing-library/user-event**: 用户交互模拟
- **jsdom**: DOM 环境模拟

## 编写新测试

1. 在 `tests/e2e/` 创建新的 `.test.tsx` 文件
2. 使用 `runtimeClientStub` 创建模拟的 Runtime 客户端
3. 使用 `render(<App />)` 渲染应用
4. 使用 `screen` 查询元素
5. 使用 `userEvent` 模拟用户交互
6. 使用 `waitFor` 等待异步操作完成

### 示例

```typescript
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { App } from "../../src/App";
import { createTauriRuntimeClient } from "../../src/runtime-client/tauri";
import { runtimeClientStub } from "../../src/test-fixtures";

vi.mock("../../src/runtime-client/tauri", () => ({
  createTauriRuntimeClient: vi.fn(),
}));

describe("E2E: My Feature", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  test("should do something", async () => {
    const client = runtimeClientStub({
      // 自定义 mock 行为
    });
    vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

    render(<App />);

    // 查询元素
    const button = await screen.findByRole("button", { name: "Click me" });

    // 用户交互
    await userEvent.click(button);

    // 断言
    await waitFor(() => {
      expect(client.someMethod).toHaveBeenCalled();
    });
  });
});
```

## 最佳实践

1. **使用语义化查询**: 优先使用 `getByRole`、`getByLabelText` 等语义化查询，而不是 `getByTestId`
2. **等待异步操作**: 使用 `await screen.findBy...` 或 `waitFor` 等待异步渲染
3. **清理 Mock**: 在 `beforeEach` 中调用 `vi.resetAllMocks()` 清理上一个测试的 mock
4. **模拟用户行为**: 使用 `userEvent` 而不是直接调用事件处理函数
5. **独立测试**: 每个测试应该独立运行，不依赖其他测试的状态
6. **描述性测试名**: 测试名应该清晰描述测试的行为和预期结果

## 调试技巧

```typescript
// 打印当前 DOM 结构
screen.debug();

// 查看元素是否存在
console.log(screen.queryByText("Some text"));

// 查看所有匹配的元素
console.log(screen.getAllByRole("button"));

// 使用 logRoles 查看可用的 ARIA 角色
import { logRoles } from "@testing-library/react";
const { container } = render(<App />);
logRoles(container);
```

## CI 集成

E2E 测试已集成到 `npm run check` 命令中，会在以下场景自动运行：

- Pre-commit hook
- CI/CD pipeline
- 本地运行 `npm run check`

## 性能考虑

- 默认测试超时时间: 10 秒（在 `vitest.e2e.config.ts` 中配置）
- 使用 jsdom 而不是真实浏览器，提升测试速度
- Mock 所有网络请求和原生 API 调用

## 故障排查

### 测试超时
```
Error: Test timed out in 10000ms.
```
**解决**: 增加超时时间或检查 `waitFor` 条件是否正确

### 元素未找到
```
Error: Unable to find an element with the text: "Some text"
```
**解决**: 使用 `screen.debug()` 查看当前 DOM，确认元素是否存在或使用正确的查询方式

### Mock 未生效
```
Error: Cannot read property 'someMethod' of undefined
```
**解决**: 确认在测试文件顶部正确 mock 了模块，并在测试中设置了返回值
