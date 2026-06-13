# ToolBlock 组件

完整的运行时工具块展示组件，用于可视化 AI 工具调用的执行过程。

## 功能特性

- ✅ **可折叠展开** - 使用 `<details>` 元素实现原生折叠/展开
- ✅ **状态指示** - 支持 running / done / error 三种状态，带视觉反馈
- ✅ **时间线展示** - 显示工具执行的输入、输出、错误历史
- ✅ **嵌套渲染** - 支持递归渲染子工具调用
- ✅ **执行时长** - 自动格式化并显示执行时间（ms/s/m）
- ✅ **深浅模式** - 完全适配项目的 Morandi 配色主题

## 类型定义

```typescript
export type ToolBlock = {
  webchatCallId: string;           // 唯一标识
  toolName: string;                 // 工具名称
  status: "running" | "done" | "error";
  children: Map<string, ToolBlock>; // 嵌套子工具
  timeline: TimelineEntry[];        // 时间线事件
  startTime: number;                // 开始时间戳
  endTime?: number;                 // 结束时间戳（可选）
};

export type TimelineEntry =
  | { type: "input"; timestamp: number; content: string }
  | { type: "output"; timestamp: number; content: string }
  | { type: "error"; timestamp: number; message: string };
```

## 使用示例

### 基本用法

```tsx
import { ToolBlock } from "./message-timeline/ToolBlock";

const toolBlock = {
  webchatCallId: "call-123",
  toolName: "search",
  status: "done",
  children: new Map(),
  timeline: [
    { type: "input", timestamp: Date.now() - 2000, content: "搜索内容" },
    { type: "output", timestamp: Date.now(), content: "找到 5 个结果" }
  ],
  startTime: Date.now() - 2000,
  endTime: Date.now()
};

<ToolBlock {...toolBlock} />
```

### 嵌套工具调用

```tsx
const childTool = { /* ... */ };
const parentTool = {
  // ...
  children: new Map([["child-id", childTool]])
};

<ToolBlock {...parentTool} />
```

### 在 MessageTimeline 中集成

```tsx
// 从 store 获取工具块
const toolBlocks = useStore(state => state.toolBlocksByJob[jobId]);

// 渲染
{Array.from(toolBlocks.values()).map(block => (
  <ToolBlock key={block.webchatCallId} {...block} />
))}
```

## 视觉设计

### 状态颜色

- **running** - 橙色边框 + 加载动画
- **done** - 绿色边框
- **error** - 红色边框

### 布局结构

```
┌─────────────────────────────────────┐
│ ▶ tool_name         1.2s     完成   │ ← summary (可点击)
├─────────────────────────────────────┤
│ 时间线                              │
│ 12:34:56 [输入] {"query": "..."}   │
│ 12:34:57 [输出] 结果内容            │
├─────────────────────────────────────┤
│ 嵌套子工具 (递归渲染)               │
│   ┌───────────────────────────┐    │
│   │ ▶ child_tool    500ms ... │    │
│   └───────────────────────────┘    │
└─────────────────────────────────────┘
```

## 样式类名

- `.runtime-tool-block` - 主容器
  - `.running` / `.done` / `.error` - 状态修饰符
- `.runtime-tool-name` - 工具名称
- `.runtime-tool-duration` - 执行时长
- `.runtime-tool-status` - 状态文本
- `.runtime-tool-preview` - 时间线容器
- `.runtime-tool-children` - 嵌套子工具容器
- `.timeline-entry` - 时间线条目
  - `.timeline-entry-input` / `.timeline-entry-output` / `.timeline-entry-error`

## 测试覆盖

✅ 10/10 测试通过

- 基本渲染（名称、状态）
- 状态样式（running / done / error）
- 时长格式化（ms / s / m）
- 折叠展开交互
- 时间线渲染（input / output / error）
- 嵌套子工具递归渲染
- 空状态处理（无时间线、无子工具）

## 文件结构

```
src/message-timeline/
├── ToolBlock.tsx              # 组件实现
├── ToolBlock.css              # 样式文件
├── ToolBlock.test.tsx         # 单元测试
└── ToolBlock.usage.example.tsx # 使用示例
```

## 样式来源

样式从 `webui/static/css/components.css` (行 1924-2123) 迁移并适配，保持与 WebUI 一致的视觉体验。

## 相关类型

类型定义位于 `src/chat-store/types.ts`:
- `ToolBlock`
- `ToolBlockStatus`
- `TimelineEntry`
