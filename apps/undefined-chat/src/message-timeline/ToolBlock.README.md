# ToolBlock 组件

完整的运行时工具块展示组件，用于可视化 AI 工具调用的执行过程。

## 功能特性

- ✅ **可折叠展开** - 使用 `<details>` 元素实现原生折叠/展开（running 自动展开，done/error 后 2s 自动折叠，用户交互后不再自动折叠）
- ✅ **状态指示** - 支持 running / done / error / cancelled 状态，带视觉反馈
- ✅ **时间线展示** - 显示工具执行的输入、输出、错误历史
- ✅ **嵌套渲染** - 支持递归渲染子工具调用
- ✅ **实时计时** - 运行中通过统一时钟 `useChatClock` 每 500ms 刷新用时，结束后定格；自动格式化（ms/s/m）
- ✅ **Agent 阶段明细** - Agent 运行中在状态位展示阶段标签（`currentStage`），并可附加阶段明细 `stageDetail`（如模型名/子步骤）
- ✅ **WebUI 一致预览** - 输入按纯文本展示；输出支持 JSON/Python 风格结构化、Markdown 渲染和附件图片预览
- ✅ **深浅模式** - 完全适配项目的 Morandi 配色主题

## 类型定义

```typescript
export type ToolBlockStatus = "running" | "done" | "error" | "cancelled";

export type ToolBlock = {
  webchatCallId: string;            // 唯一标识
  toolName: string;                 // 工具名称
  status: ToolBlockStatus;
  isAgent?: boolean;                // 是否为 Agent（决定 kind 标签与阶段展示）
  uiHint?: string;                  // UI 提示，附加为容器修饰类名
  argumentsPreview?: string;        // 输入参数预览
  resultPreview?: string;           // 结果预览（结构化/Markdown/附件图片）
  currentStage?: string;            // Agent 当前阶段（运行中展示标签）
  stageDetail?: string;             // 阶段明细（如模型名/子步骤）
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

### 历史回放（calls / events 多级回退）

实时运行的工具块由 store 维护；历史消息则由 `MessageTimelineContent` 消费一条已交错好的
`timeline`，其中 `type === "call"` 的条目经 `convertHistoryToolCallToToolBlock` 转换为本组件所需的
`ToolBlock`（映射 `arguments_preview`/`result_preview`/`is_agent`/`current_stage`/`current_stage_detail`
等字段，并按 `duration_ms` 反推 `startTime`）。

`timeline` 由 `MessageTimeline` 的 `buildHistoryTimeline` 按可用性多级回退构建：

1. `webchat.timeline`：首选，后端已交错好的完整时间线；
2. `webchat.calls`：仅有调用树时，逐根节点包成 `call` 条目，正文走 `fallbackContent` 兜底；
3. `webchat.events`：最原始，重建顶层 message + call。

三者皆空时回退普通正文渲染。

## 视觉设计

### 状态颜色

- **running** - 橙色边框 + 加载动画
- **done** - 绿色边框
- **error** - 红色边框

### 布局结构

```
┌─────────────────────────────────────┐
│ ▶ tool_name    1.2s   完成    Tool  │ ← summary (可点击；Agent 运行中显示阶段标签)
├─────────────────────────────────────┤
│ 输入                                │
│   {"query": "..."}                  │ ← argumentsPreview (<pre>)
├─────────────────────────────────────┤
├─────────────────────────────────────┤
│ 时间线 + 嵌套子工具 (递归渲染)      │
│ 12:34:56 [输入] {"query": "..."}    │
│   ┌───────────────────────────┐    │
│   │ ▶ child_tool    500ms ... │    │
│   └───────────────────────────┘    │
├─────────────────────────────────────┤
│ 输出                                │
│   key: value  ...                   │ ← resultPreview (结构化/Markdown/附件图片)
└─────────────────────────────────────┘
```

## 样式类名

- `.runtime-tool-block` - 主容器
  - `.running` / `.done` / `.error` - 状态修饰符
  - `.is-agent` / `.is-tool` - 类型修饰符（按 `isAgent` 区分）
  - `uiHint` 经下划线转连字符后追加为修饰类名（如 `runtime-tool-block ... agent-task`）
- `.runtime-tool-name` - 工具名称
- `.runtime-tool-duration` - 执行时长
- `.runtime-tool-status` - 状态/阶段文本（Agent 运行中显示阶段标签）
- `.runtime-tool-kind` - 类型标签（Agent / Tool）
- `.runtime-tool-preview` - 输入/输出预览容器
  - `.runtime-tool-preview-label` / `.runtime-tool-preview-body` - 预览标题 / 内容
  - `.runtime-tool-preview-body.is-structured` - 结构化结果内容容器
- `.runtime-tool-structured-list` - WebUI 同名结构化结果根
  - `.runtime-tool-structured-row` - 结构化结果行
  - `.runtime-tool-key` / `.runtime-tool-value` - 键 / 值
  - `.runtime-tool-value.string` / `.number` / `.boolean` / `.muted` - 标量类型修饰类
- `.runtime-tool-children` - 嵌套子工具与时间线容器
- `.timeline-entry` - 时间线条目
  - `.timeline-entry-input` / `.timeline-entry-output` / `.timeline-entry-error`

## 测试覆盖

- 基本渲染（名称、状态）
- 状态样式（running / done / error）
- 时长格式化（ms / s / m）
- 折叠展开交互
- 时间线渲染（input / output / error）
- 嵌套子工具递归渲染（单个 / 多个）
- 空状态处理（无时间线、无子工具）
- 结果预览：JSON/Python 风格结构化、非结构化 Markdown、附件图片标签 fallback
- Agent 运行中在阶段标签后展示 `stageDetail`

## 文件结构

```
src/message-timeline/
├── ToolBlock.tsx              # 组件实现
├── ToolBlock.css              # 样式文件
└── ToolBlock.test.tsx         # 单元测试
```

## 样式来源

样式从 `webui/static/css/components.css` 的 `.runtime-tool-*` 规则迁移并适配，保持与 WebUI 一致的视觉体验。

## 相关类型

类型定义位于 `src/chat-store/types.ts`:
- `ToolBlock`
- `ToolBlockStatus`
- `TimelineEntry`
