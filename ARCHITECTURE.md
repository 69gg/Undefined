# Undefined 详细架构图

## 一、完整系统架构图

```mermaid
graph TB
    %% ==================== 外部实体 ====================
    subgraph External["外部实体层"]
        User([用户 User])
        Admin([管理员 Admin])
        OneBotServer["OneBot 协议端<br/>(NapCat / Lagrange.Core)"]
        LLM_API["大模型 API 服务商<br/>(OpenAI / Claude / DeepSeek / etc.)"]
    end

    %% ==================== 核心入口层 ====================
    subgraph EntryPoint["核心入口层 (src/Undefined/)"]
        Main["main.py<br/>启动入口"]
        ConfigLoader["ConfigManager<br/>配置管理器<br/>[config/manager.py + loader.py]"]
        ConfigModels["配置模型<br/>[config/models.py]<br/>ChatModelConfig<br/>VisionModelConfig<br/>SecurityModelConfig<br/>AgentModelConfig"]
        OneBotClient["OneBotClient<br/>WebSocket 客户端<br/>[onebot.py]"]
        Context["RequestContext<br/>请求上下文<br/>[context.py]"]
        WebUI["webui.py<br/>配置控制台<br/>[src/Undefined/webui.py]"]
    end

    %% ==================== 消息处理层 ====================
    subgraph MessageLayer["消息处理层 (src/Undefined/)"]
        MessageHandler["MessageHandler<br/>消息处理器<br/>[handlers.py]"]
        
        subgraph SecurityLayer["安全防线 (services/)"]
            SecurityService["SecurityService<br/>安全服务<br/>• 注入攻击检测<br/>• 速率限制<br/>[security.py]"]
            InjectionAgent["InjectionResponseAgent<br/>注入响应生成<br/>[injection_response_agent.py]"]
        end
        
        CommandDispatcher["CommandDispatcher<br/>命令分发器<br/>• /help /stats /lsadmin<br/>• /addadmin /rmadmin<br/>• /bugfix /lsfaq<br/>[services/command.py]"]
        
        subgraph QueueSystem["车站-列车 队列系统 (services/)"]
            AICoordinator["AICoordinator<br/>AI 协调器<br/>• Prompt 构建<br/>• 队列管理<br/>• 回复执行<br/>[ai_coordinator.py]"]
            QueueManager["QueueManager<br/>队列管理器<br/>[queue_manager.py]"]
            
            subgraph ModelQueues["ModelQueue 队列组 (按模型隔离)"]
                Q_SuperAdmin["超级管理员队列<br/>优先级: 最高"]
                Q_Private["私聊队列<br/>优先级: 高"]
                Q_Mention["群聊 @队列<br/>优先级: 中"]
                Q_Normal["群聊普通队列<br/>优先级: 普通<br/>自动修剪: 保留最新2条"]
            end
            
            DispatcherLoop[("1Hz 非阻塞<br/>发车循环<br/>每秒自动发车")]
        end
    end

    %% ==================== AI 核心能力层 ====================
    subgraph AILayer["AI 核心能力层 (src/Undefined/ai/)"]
        AIClient["AIClient<br/>AI 客户端主入口<br/>[client.py]<br/>• 技能热重载 • MCP 初始化<br/>• Agent intro 生成"]
        
        subgraph AIComponents["AI 组件"]
            PromptBuilder["PromptBuilder<br/>提示词构建器<br/>[prompts.py]"]
            ModelRequester["ModelRequester<br/>模型请求器<br/>[llm.py]<br/>• OpenAI SDK • 工具清理<br/>• Thinking 提取"]
            ToolManager["ToolManager<br/>工具管理器<br/>[tooling.py]<br/>• 工具执行 • Agent 工具合并<br/>• MCP 工具注入"]
            MultimodalAnalyzer["MultimodalAnalyzer<br/>多模态分析器<br/>[multimodal.py]<br/>• 图片/音频/视频"]
            SummaryService["SummaryService<br/>总结服务<br/>[summaries.py]<br/>• 聊天记录总结<br/>• 标题生成"]
            TokenCounter["TokenCounter<br/>Token 统计<br/>[tokens.py]"]
            Parsing["Parsing<br/>响应解析<br/>[parsing.py]"]
        end
    end

    %% ==================== 技能系统层 ====================
    subgraph SkillsLayer["Skills 技能系统 (src/Undefined/skills/)"]
        subgraph RegistryLayer["注册表核心"]
            ToolRegistry["ToolRegistry<br/>工具注册表<br/>[registry.py]<br/>• 延迟加载 • 热重载支持<br/>• 执行统计"]
            AgentRegistry["AgentRegistry<br/>Agent 注册表<br/>[registry.py]<br/>• Agent 发现 • 工具聚合"]
            AgentToolRegistry["AgentToolRegistry<br/>Agent 专用工具注册表<br/>[agents/agent_tool_registry.py]<br/>• MCP 支持"]
            IntroGenerator["IntroGenerator<br/>Agent 介绍生成器<br/>[agents/intro_generator.py]<br/>• 自动 hash 检测<br/>• intro.generated.md"]
        end
        
        subgraph AtomicTools["基础工具 (skills/tools/)"]
            T_End["end<br/>结束对话"]
            T_Python["python_interpreter<br/>Python 解释器"]
            T_Time["get_current_time<br/>获取当前时间"]
            T_GetPicture["get_picture<br/>获取图片"]
            T_GetUserInfo["get_user_info<br/>获取用户信息"]
        end
        
        subgraph Toolsets["工具集 (skills/toolsets/)"]
            TS_Group["group.*<br/>• get_member_list<br/>• get_member_info<br/>• get_honor_info<br/>• get_files"]
            TS_Messages["messages.*<br/>• send_message<br/>• get_recent_messages<br/>• get_forward_msg"]
            TS_Memory["memory.*<br/>• add / delete<br/>• list / update"]
            TS_Notices["notices.*<br/>• list / get / stats"]
            TS_Render["render.*<br/>• render_html<br/>• render_latex<br/>• render_markdown"]
            TS_Scheduler["scheduler.*<br/>• create_schedule_task<br/>• delete_schedule_task<br/>• list_schedule_tasks"]
            TS_MCP["mcp.*<br/>MCP 工具集"]
        end
        
        subgraph IntelligentAgents["智能体 Agents (skills/agents/)"]
            A_Info["info_agent<br/>信息查询助手<br/>(15个工具)<br/>• weather_query<br/>• *hot 热搜<br/>• gold_price<br/>• whois"]
            A_Social["social_agent<br/>社交媒体助手<br/>(8个工具)<br/>• bilibili_search<br/>• music_*<br/>• video_recommend"]
            A_Web["web_agent<br/>网络搜索助手<br/>(3个工具 + MCP)<br/>• web_search<br/>• crawl_webpage<br/>• Playwright MCP"]
            A_File["file_analysis_agent<br/>文件分析助手<br/>(14个工具)<br/>• extract_* (PDF/Word/Excel/PPT)<br/>• analyze_code<br/>• analyze_multimodal"]
            A_Naga["naga_code_analysis_agent<br/>NagaAgent 代码分析<br/>(7个工具)<br/>• read_file / glob<br/>• search_file_content"]
            A_Entertainment["entertainment_agent<br/>娱乐助手<br/>(10个工具)<br/>• ai_draw_one<br/>• horoscope<br/>• novel_search"]
        end
        
        subgraph MCPIntegration["MCP 集成 (src/Undefined/mcp/)"]
            MCPRegistry["MCPToolRegistry<br/>MCP 工具注册表<br/>[registry.py]<br/>• 连接 MCP Server<br/>• 工具转换"]
            MCP_Config["MCP 配置<br/>config/mcp.json<br/>(全局配置)"]
            MCP_Agent_Private["Agent 私有 MCP<br/>mcp.json<br/>(按 Agent)"]
        end
    end

    %% ==================== 存储与上下文层 ====================
    subgraph StorageLayer["存储与上下文层 (src/Undefined/)"]
        subgraph ContextLayer["上下文管理"]
            RequestContext["RequestContext<br/>[context.py]<br/>• UUID 追踪<br/>• 资源容器<br/>• 自动传播"]
            ContextFilter["RequestContextFilter<br/>日志过滤器<br/>• request_id<br/>• group_id / user_id"]
            ResourceRegistry["ContextResourceRegistry<br/>资源注册表<br/>[context_resource_registry.py]<br/>• 动态扫描"]
        end
        
        subgraph StorageComponents["存储组件"]
            HistoryManager["MessageHistoryManager<br/>消息历史管理<br/>[utils/history.py]<br/>• 懒加载<br/>• 10000条限制"]
            MemoryStorage["MemoryStorage<br/>长期记忆存储<br/>[memory.py]<br/>• 500条上限<br/>• 自动去重"]
            EndSummaryStorage["EndSummaryStorage<br/>短期总结存储<br/>[end_summary_storage.py]"]
            FAQStorage["FAQStorage<br/>FAQ 存储<br/>[faq.py]<br/>• data/faq/{group_id}/"]
            ScheduledTaskStorage["ScheduledTaskStorage<br/>定时任务存储<br/>[scheduled_task_storage.py]"]
            TokenUsageStorage["TokenUsageStorage<br/>Token 使用统计<br/>[token_usage_storage.py]<br/>• 自动归档<br/>• gzip 压缩"]
        end
        
        subgraph IOLayer["异步 IO 层 (src/Undefined/utils/)"]
        IOUtils["IO 工具<br/>[io.py]<br/>• write_json<br/>• read_json<br/>• append_line<br/>• 文件锁 (flock/msvcrt)"]
            SchedulerUtils["调度器工具<br/>[scheduler.py]<br/>• crontab 解析"]
            CacheUtils["缓存工具<br/>[cache.py]<br/>• 定期清理"]
            SenderUtils["Sender 工具<br/>[sender.py]"]
        end
    end

    %% ==================== 数据持久化层 ====================
    subgraph Persistence["数据持久化层 (data/)"]
        Dir_History["history/<br/>• group_{id}.json<br/>• private_{id}.json"]
        Dir_FAQ["faq/<br/>• {group_id}/<br/>  - {date}-{seq}.json"]
        Dir_TokenUsage["token_usage_archives/<br/>• token_usage.jsonl<br/>• *.jsonl.gz"]
        File_Memory["memory.json<br/>(长期记忆)"]
        File_EndSummary["end_summaries.json<br/>(短期总结)"]
        File_ScheduledTasks["scheduled_tasks.json<br/>(定时任务)"]
        Dir_Logs["logs/<br/>• bot.log<br/>• 轮转日志"]
        File_Config["config.toml<br/>config.local.json"]
    end

    %% ==================== 资源文件层 ====================
    subgraph Resources["资源文件层 (res/)"]
        Prompts["prompts/<br/>• undefined.xml<br/>• agent_self_intro.txt<br/>• analyze_multimodal.txt"]
        Intros["agents/intro/<br/>• intro.md<br/>• intro.generated.md"]
    end

    %% ==================== 连接线 ====================
    %% 外部实体到核心入口
    User -->|"消息"| OneBotServer
    Admin -->|"指令"| OneBotServer
    OneBotServer <-->|"WebSocket<br/>Event / API"| OneBotClient
    
    %% 核心入口层内部
    Main -->|"初始化"| ConfigLoader
    Main -->|"创建"| OneBotClient
    Main -->|"创建"| AIClient
    ConfigLoader --> ConfigModels
    ConfigLoader -->|"读取"| File_Config
    WebUI -->|"读写"| File_Config
    OneBotClient -->|"消息事件"| MessageHandler
    
    %% 消息处理层
    MessageHandler -->|"1. 安全检测"| SecurityService
    SecurityService -.->|"API 调用"| LLM_API
    SecurityService -->|"注入攻击"| InjectionAgent
    
    MessageHandler -->|"2. 指令?"| CommandDispatcher
    CommandDispatcher -->|"执行结果"| OneBotClient
    
    MessageHandler -->|"3. 自动回复"| AICoordinator
    AICoordinator -->|"创建上下文"| RequestContext
    AICoordinator -->|"入队"| QueueManager
    QueueManager -->|"分发"| ModelQueues
    ModelQueues -->|"轮询取值"| DispatcherLoop
    DispatcherLoop -->|"异步执行"| AIClient
    
    %% AI 核心能力层
    AIClient --> PromptBuilder
    AIClient --> ModelRequester
    AIClient --> ToolManager
    AIClient --> MultimodalAnalyzer
    AIClient --> SummaryService
    AIClient --> TokenCounter
    
    ModelRequester <-->|"API 请求"| LLM_API
    PromptBuilder -->|"注入记忆"| MemoryStorage
    PromptBuilder -->|"注入总结"| EndSummaryStorage
    PromptBuilder -->|"注入历史"| HistoryManager
    
    ToolManager -->|"获取工具"| ToolRegistry
    ToolManager -->|"获取 Agent"| AgentRegistry
    ToolManager -->|"获取 MCP"| MCPRegistry
    
    %% 技能系统层
    ToolRegistry --> AtomicTools
    ToolRegistry --> Toolsets
    AgentRegistry --> IntelligentAgents
    AgentRegistry -->|"触发"| IntroGenerator
    
    A_Web -->|"私有 MCP"| MCP_Agent_Private
    MCP_Agent_Private -->|"连接"| MCPRegistry
    MCP_Config -->|"全局 MCP"| MCPRegistry
    
    %% 存储层
    RequestContext -->|"日志增强"| ContextFilter
    RequestContext -->|"资源扫描"| ResourceRegistry
    
    MessageHandler -->|"保存消息"| HistoryManager
    AICoordinator -->|"记录统计"| TokenUsageStorage
    CommandDispatcher -->|"FAQ 操作"| FAQStorage
    
    %% IO 层到持久化
    HistoryManager -->|"异步读写"| IOUtils
    MemoryStorage -->|"异步读写"| IOUtils
    TokenUsageStorage -->|"异步读写<br/>自动归档"| IOUtils
    FAQStorage -->|"异步读写"| IOUtils
    ScheduledTaskStorage -->|"异步读写"| IOUtils
    
    IOUtils --> Dir_History
    IOUtils --> File_Memory
    IOUtils --> File_EndSummary
    IOUtils --> Dir_TokenUsage
    IOUtils --> Dir_FAQ
    IOUtils --> File_ScheduledTasks
    
    %% 资源文件
    PromptBuilder -->|"加载"| Prompts
    IntroGenerator -->|"生成"| Intros
    IntelligentAgents -->|"读取"| Intros
    
    %% Agent 递归调用
    IntelligentAgents -->|"递归调用"| AIClient
    
    %% 样式定义
    classDef external fill:#ffebee,stroke:#c62828,stroke-width:2px
    classDef core fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    classDef message fill:#fff3e0,stroke:#ef6c00,stroke-width:2px
    classDef ai fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px
    classDef skills fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    classDef storage fill:#e0f7fa,stroke:#00838f,stroke-width:2px
    classDef io fill:#fce4ec,stroke:#c2185b,stroke-width:1px
    classDef persistence fill:#f5f5f5,stroke:#616161,stroke-width:1px
    classDef resource fill:#fff8e1,stroke:#ff8f00,stroke-width:1px
    classDef queue fill:#e8eaf6,stroke:#3949ab,stroke-width:2px
    classDef agent fill:#e1f5fe,stroke:#0277bd,stroke-width:2px
    
    class User,Admin,OneBotServer,LLM_API external
    class Main,ConfigLoader,ConfigModels,OneBotClient,Context,WebUI core
    class MessageHandler,SecurityService,InjectionAgent,CommandDispatcher,AICoordinator message
    class AIClient,PromptBuilder,ModelRequester,ToolManager,MultimodalAnalyzer,SummaryService,TokenCounter,Parsing ai
    class ToolRegistry,AgentRegistry,AgentToolRegistry,IntroGenerator skills
    class RequestContext,ContextFilter,ResourceRegistry,HistoryManager,MemoryStorage,EndSummaryStorage,FAQStorage,ScheduledTaskStorage,TokenUsageStorage storage
    class IOUtils,SchedulerUtils,CacheUtils,SenderUtils io
    class Dir_History,Dir_FAQ,Dir_TokenUsage,File_Memory,File_EndSummary,File_ScheduledTasks,Dir_Logs,File_Config persistence
    class Prompts,Intros resource
    class QueueManager,ModelQueues,DispatcherLoop queue
    class A_Info,A_Social,A_Web,A_File,A_Naga,A_Entertainment agent
```

## 二、数据流向图

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户
    participant OB as OneBot<br/>协议端
    participant MC as main.py<br/>入口
    participant OH as OneBotClient
    participant MH as MessageHandler
    participant SS as SecurityService
    participant CD as CommandDispatcher
    participant AC as AICoordinator
    participant QM as QueueManager
    participant AI as AIClient
    participant LLM as 大模型API
    participant TM as ToolManager
    participant ST as Storage

    %% 消息接收流程
    U->>OB: 发送消息
    OB->>OH: WebSocket 转发
    OH->>MC: 触发消息事件
    MC->>MH: handle_message()
    
    %% 安全检测
    MH->>SS: detect_injection()
    SS->>LLM: 安全模型检测
    LLM-->>SS: 检测结果
    alt 检测到注入
        SS->>MH: 拦截并响应
    else 安全
        %% 指令处理
        MH->>CD: 解析斜杠命令
        alt 是命令
            CD->>ST: FAQ/管理员操作
            CD-->>OB: 返回结果
            OB->>U: 发送响应
        else 是AI消息
            %% AI处理流程
            MH->>AC: handle_auto_reply()
            
            %% 上下文创建
            AC->>AC: 创建 RequestContext
            AC->>ST: 保存历史记录
            AC->>QM: add_group_mention/normal_request()
            
            %% 队列处理
            QM->>QM: 1Hz 发车循环
            QM->>AC: execute_reply()
            
            %% AI 调用
            AC->>AI: ask()
            
            %% Prompt 构建
            AI->>ST: 加载记忆
            AI->>ST: 加载历史
            AI->>ST: 加载总结
            AI->>AI: build_messages()
            
            %% 模型请求
            AI->>LLM: chat.completions.create()
            
            %% 工具调用循环
            loop 最多 1000 次迭代
                LLM-->>AI: 返回 tool_calls
                AI->>TM: execute_tool()
                
                alt 是普通工具
                    TM->>ST: 执行工具
                    TM-->>AI: 工具结果
                else 是 Agent
                    TM->>AI: 递归调用
                    AI->>LLM: 子请求
                    LLM-->>AI: 返回
                    AI-->>TM: Agent 结果
                    TM-->>AI: 合并结果
                end
                
                AI->>LLM: 继续请求
            end
            
            LLM-->>AI: 最终回复
            AI->>ST: 记录 Token 使用
            AI-->>AC: 返回回复内容
            
            AC->>ST: 保存总结
            AC->>OH: 发送消息
            OH->>OB: WebSocket API
            OB->>U: 显示回复
        end
    end
```

## 三、Skills 系统架构图

```mermaid
graph TB
    subgraph SkillsArchitecture["Skills 系统架构"]
        AIClient["AIClient<br/>主入口"]
        
        subgraph RegistrySystem["注册表系统"]
            BaseRegistry["BaseRegistry<br/>基础注册表<br/>• 延迟加载<br/>• 热重载<br/>• 执行统计<br/>[registry.py]"]
            ToolRegistry["ToolRegistry<br/>工具注册表"]
            AgentRegistry["AgentRegistry<br/>Agent 注册表"]
            AgentToolReg["AgentToolRegistry<br/>Agent 专用注册表<br/>• MCP 支持"]
        end
        
        subgraph ToolsLayer["Tools 层"]
            AtomicTools["原子工具<br/>(skills/tools/)"]
            Toolsets["工具集<br/>(skills/toolsets/)"]
            
            subgraph ToolsetsDetail["工具集详情"]
                TGroup["group.*<br/>群管理"]
                TMsg["messages.*<br/>消息"]
                TMem["memory.*<br/>记忆"]
                TNotice["notices.*<br/>公告"]
                TRender["render.*<br/>渲染"]
                TSched["scheduler.*<br/>定时任务"]
                TMCP["mcp.*<br/>MCP"]
            end
        end
        
        subgraph AgentsLayer["Agents 层"]
            InfoAgent["info_agent<br/>信息查询"]
            SocialAgent["social_agent<br/>社交媒体"]
            WebAgent["web_agent<br/>网络搜索<br/>• MCP Playwright"]
            FileAgent["file_analysis_agent<br/>文件分析"]
            NagaAgent["naga_code_analysis_agent<br/>代码分析"]
            EntAgent["entertainment_agent<br/>娱乐"]
        end
        
        subgraph IntroSystem["Intro 系统"]
            IntroGen["IntroGenerator<br/>介绍生成器"]
            IntroUtils["IntroUtils<br/>合并工具"]
            IntroFiles["intro.md +<br/>intro.generated.md"]
        end
        
        subgraph MCPLayer["MCP 层"]
            MCPReg["MCPToolRegistry<br/>MCP 注册表"]
            MCPGlobal["全局 MCP<br/>config/mcp.json"]
            MCPAgent["Agent 私有 MCP<br/>{agent}/mcp.json"]
        end
    end
    
    %% 连接
    AIClient --> ToolRegistry
    AIClient --> AgentRegistry
    AIClient --> IntroGen
    
    BaseRegistry --> ToolRegistry
    BaseRegistry --> AgentRegistry
    ToolRegistry --> AtomicTools
    ToolRegistry --> Toolsets
    Toolsets --> ToolsetsDetail
    AgentRegistry --> AgentsLayer
    
    AgentRegistry --> AgentToolReg
    AgentToolReg --> InfoAgent
    AgentToolReg --> SocialAgent
    AgentToolReg --> WebAgent
    AgentToolReg --> FileAgent
    AgentToolReg --> NagaAgent
    AgentToolReg --> EntAgent
    
    WebAgent --> MCPAgent
    MCPAgent --> MCPReg
    MCPGlobal --> MCPReg
    
    IntroGen --> IntroFiles
    IntroUtils --> IntroFiles
    AgentsLayer --> IntroUtils
```

## 四、存储架构图

```mermaid
graph LR
    subgraph StorageArchitecture["存储架构"]
        subgraph Context["上下文"]
            RC["RequestContext<br/>• UUID<br/>• 资源容器"]
        end
        
        subgraph IOLayer["IO 层<br/>[utils/io.py]"]
            IO["异步 IO<br/>• write_json<br/>• read_json<br/>• append_line<br/>• 文件锁"]
        end
        
        subgraph StorageTypes["存储类型"]
            History["MessageHistoryManager<br/>data/history/<br/>• 懒加载<br/>• 10000条限制"]
            Memory["MemoryStorage<br/>data/memory.json<br/>• 500条上限"]
            EndSummary["EndSummaryStorage<br/>data/end_summaries.json"]
            FAQ["FAQStorage<br/>data/faq/{group_id}/<br/>• ID: YYYYMMDD-NNN"]
            Tasks["ScheduledTaskStorage<br/>data/scheduled_tasks.json<br/>• Cron 格式"]
            TokenUsage["TokenUsageStorage<br/>data/token_usage.jsonl<br/>• 自动归档<br/>• gzip 压缩"]
        end
        
        subgraph Persistence["持久化"]
            FS["文件系统"]
        end
    end
    
    %% 连接
    RC -->|"记录统计"| TokenUsage
    RC -->|"保存消息"| History
    RC -->|"读写"| Memory
    RC -->|"读写"| EndSummary
    RC -->|"FAQ 操作"| FAQ
    RC -->|"任务管理"| Tasks
    
    TokenUsage --> IO
    History --> IO
    Memory --> IO
    EndSummary --> IO
    FAQ --> IO
    Tasks --> IO
    
    IO -->|"异步安全"| FS
```

## 五、队列模型详解

```mermaid
graph TB
    subgraph QueueModel["车站-列车 队列模型"]
        subgraph QueueManager["QueueManager<br/>队列管理器"]
            direction TB
            Start["启动"]
            Loop["1Hz 循环<br/>每秒发车一次"]
            Check["检查各队列"]
            Dispatch["分发请求"]
            Exec["执行回调"]
            
            Start --> Loop
            Loop --> Check
            Check -->|"有请求"| Dispatch
            Dispatch --> Exec
            Exec --> Loop
        end
        
        subgraph ModelQueues["ModelQueue<br/>按模型隔离的队列组"]
            direction TB
            
            subgraph AdminQueue["超级管理员队列"]
                QA1["请求 1"]
                QA2["请求 2"]
                QA3["请求 3"]
                PriorityA["优先级: 最高"]
            end
            
            subgraph PrivateQueue["私聊队列"]
                QP1["请求 1"]
                QP2["请求 2"]
                PriorityP["优先级: 高"]
            end
            
            subgraph MentionQueue["群聊 @队列"]
                QM1["请求 1"]
                QM2["请求 2"]
                PriorityM["优先级: 中"]
            end
            
            subgraph NormalQueue["群聊普通队列"]
                QN1["请求 1"]
                QN2["请求 2"]
                QN3["请求 3"]
                QN_N["...最多保留最新2条"]
                PriorityN["优先级: 普通<br/>自动修剪"]
            end
        end
        
        subgraph Features["特性"]
            F1["非阻塞: 即使前一个请求未完成,<br/>新请求也会按时分发"]
            F2["优先级: 四级优先级,<br/>确保重要消息优先响应"]
            F3["隔离性: 每个模型独立队列,<br/>互不干扰"]
            F4["自动修剪: 普通队列超过10条时,<br/>只保留最新2条"]
        end
    end
    
    %% 样式
    style AdminQueue fill:#ffebee,stroke:#c62828
    style PrivateQueue fill:#fff3e0,stroke:#ef6c00
    style MentionQueue fill:#e8f5e9,stroke:#2e7d32
    style NormalQueue fill:#e3f2fd,stroke:#1565c0
```

## 六、Agent 结构详解

```mermaid
graph TB
    subgraph AgentStructure["Agent 标准结构"]
        subgraph FileStructure["文件结构"]
            Config["config.json<br/>工具定义<br/>(OpenAI Function)"]
            Handler["handler.py<br/>执行逻辑<br/>• 多轮迭代<br/>• 工具并发"]
            Prompt["prompt.md<br/>系统提示词"]
            Intro["intro.md<br/>手动介绍"]
            IntroGen["intro.generated.md<br/>自动生成介绍"]
            MCP["mcp.json<br/>私有 MCP (可选)"]
        end
        
        subgraph ExecutionFlow["执行流程"]
            Input["用户请求"]
            BuildTools["构建工具列表<br/>• 本地工具<br/>• MCP 工具"]
            Iteration["多轮迭代<br/>最多 20-30 次"]
            Parallel["并发执行<br/>asyncio.gather"]
            Output["返回结果"]
            
            Input --> BuildTools
            BuildTools --> Iteration
            Iteration -->|"调用工具"| Parallel
            Parallel -->|"结果"| Iteration
            Iteration -->|"完成"| Output
        end
        
        subgraph IntroGeneration["Intro 生成流程"]
            Detect["检测文件变更<br/>• config.json<br/>• handler.py<br/>• tools/"]
            Hash["计算 Hash"]
            Queue["加入生成队列"]
            Generate["AI 生成介绍<br/>(IntroGenerator)"]
            Merge["合并 intro.md<br/>+ intro.generated.md"]
            Cache["保存 Hash 缓存"]
            
            Detect --> Hash
            Hash -->|"变更"| Queue
            Queue --> Generate
            Generate --> Merge
            Merge --> Cache
        end
    end
```

## 七、MCP 集成架构

```mermaid
graph LR
    subgraph MCPArchitecture["MCP 集成架构"]
        subgraph GlobalMCP["全局 MCP"]
            Config["config/mcp.json<br/>全局配置"]
            MCPReg["MCPToolRegistry<br/>mcp/registry.py"]
        end
        
        subgraph AgentMCP["Agent 私有 MCP"]
            WebAgent["web_agent"]
            WebMCP["web_agent/mcp.json<br/>Playwright MCP"]
        end
        
        subgraph MCPServer["MCP Server"]
            Playwright["@playwright/mcp@latest<br/>• 网页截图<br/>• 浏览器自动化"]
            Filesystem["@modelcontextprotocol/server-filesystem<br/>• 文件访问"]
            Other["其他 MCP Server..."]
        end
        
        subgraph ToolExecution["工具执行"]
            TM["ToolManager<br/>ai/tooling.py"]
            StdTools["标准工具"]
            MCPTools["MCP 工具"]
        end
    end
    
    %% 连接
    Config --> MCPReg
    WebAgent -->|"临时加载"| WebMCP
    WebMCP -->|"连接"| Playwright
    MCPReg -->|"连接"| Filesystem
    MCPReg -->|"连接"| Other
    
    MCPReg -->|"注册"| MCPTools
    TM --> StdTools
    TM --> MCPTools
```

## 八、核心配置一览

| 配置类别 | 关键配置项 | 说明 |
|---------|-----------|------|
| **基础配置** | `core.bot_qq`, `core.superadmin_qq`, `onebot.ws_url` | 机器人身份和连接 |
| **模型配置** | `models.chat` / `models.vision` / `models.agent` / `models.security` | 四类模型独立配置 |
| **功能开关** | `skills.hot_reload`, `skills.intro_autogen_enabled` | 热重载和自动生成 |
| **日志配置** | `logging.level`, `logging.file_path`, `logging.max_size_mb` | 日志系统 |
| **MCP 配置** | `mcp.config_path` | MCP 配置文件路径 |
| **存储配置** | `token_usage.*` | Token 归档和清理策略 |
| **思考链** | `*.thinking_enabled` | 思维链支持 |
| **DeepSeek** | `*.deepseek_new_cot_support` | DeepSeek CoT 兼容 |
| **WebUI** | `webui.url`, `webui.port`, `webui.password` | 配置控制台 |

## 九、架构详解

### 8层架构分层

1. **外部实体层**：用户、管理员、OneBot 协议端 (NapCat/Lagrange.Core)、大模型 API 服务商
2. **核心入口层**：main.py 启动入口、配置管理器 (config/loader.py)、OneBotClient (onebot.py)、RequestContext (context.py)
3. **消息处理层**：MessageHandler (handlers.py)、SecurityService (security.py)、CommandDispatcher (services/command.py)、AICoordinator (ai_coordinator.py)、QueueManager (queue_manager.py)
4. **AI 核心能力层**：AIClient (client.py)、PromptBuilder (prompts.py)、ModelRequester (llm.py)、ToolManager (tooling.py)、MultimodalAnalyzer (multimodal.py)、SummaryService (summaries.py)、TokenCounter (tokens.py)
5. **存储与上下文层**：MessageHistoryManager (utils/history.py, 10000条限制)、MemoryStorage (memory.py, 500条上限)、EndSummaryStorage、FAQStorage、ScheduledTaskStorage、TokenUsageStorage (自动归档)
6. **技能系统层**：ToolRegistry (registry.py)、AgentRegistry、6个 Agents (共64个工具)、7类 Toolsets
7. **异步 IO 层**：统一 IO 工具 (utils/io.py)，包含 write_json、read_json、append_line、跨平台文件锁 (flock/msvcrt)
8. **数据持久化层**：历史数据目录、FAQ 目录、Token 归档目录、记忆文件、总结文件、定时任务文件

### "车站-列车" 队列模型

针对高并发消息处理，Undefined 实现了全新的 **ModelQueue** 调度机制：

*   **多模型隔离**：每个 AI 模型拥有独立的请求队列组（"站台"），互不干扰。
*   **非阻塞发车**：实现了 **1Hz** 的非阻塞调度循环（"列车"）。每秒钟列车都会准时出发，带走一个请求到后台异步处理。
*   **高可用性**：即使前一个请求仍在处理（如耗时的网络搜索），新的请求也会按时被分发，不会造成队列堵塞。
*   **优先级管理**：支持四级优先级（超级管理员 > 私聊 > 群聊@ > 群聊普通），确保重要消息优先响应。

### 6个智能体 Agent

| Agent | 功能定位 | 工具数量 | 核心能力 |
|-------|---------|---------|---------|
| **info_agent** | 信息查询助手 | 15个 | 天气查询、热搜榜单、金价、网络检测等 |
| **social_agent** | 社交媒体助手 | 8个 | B站搜索、音乐查询、随机视频推荐等 |
| **web_agent** | 网络搜索助手 | 3个 + MCP | 网页搜索、爬虫、Playwright MCP |
| **file_analysis_agent** | 文件分析助手 | 14个 | PDF/Word/Excel/PPT解析、代码分析、多模态分析 |
| **naga_code_analysis_agent** | NagaAgent 代码分析 | 7个 | 代码库浏览、文件搜索、目录遍历 |
| **entertainment_agent** | 娱乐助手 | 10个 | AI 绘图、星座运势、小说搜索等 |

### Skills 插件系统

- **Tools (基础工具)**：原子化的功能单元，如 `send_message`, `get_history`。
- **Toolsets (复合工具集)**：7大类工具集 (group, messages, memory, notices, render, scheduler, mcp)。
- **延迟加载 + 热重载**：`handler.py` 仅在首次调用时导入；当 `skills/` 下的 `config.json`/`handler.py` 发生变更时会自动重新加载。
- **Agent 自我介绍自动生成**：启动时按 Agent 代码/配置 hash 生成 `intro.generated.md` 并与 `intro.md` 合并。

### 统一 IO 层与异步存储

-   **统一 IO 工具** (`src/Undefined/utils/io.py`)：任何涉及磁盘读写的操作（JSON 读写、行追加）都必须通过该层，内部使用 `asyncio.to_thread` 将阻塞调用移出主线程。
-   **内核级文件锁**：引入跨平台文件锁 (Linux/macOS 使用 `flock`，Windows 使用 `msvcrt`)。在高并发写入 Token 记录或记忆时，系统会自动进行排队并保持原子性，避免文件损坏或主循环假死。
-   **存储组件异步化**：所有核心存储类（Memory, FAQ, Tasks）现已全面提供异步接口，确保机器人响应不受磁盘延迟影响。

---

**架构图版本**: v2.11.0
**更新日期**: 2026-02-03  
**基于代码版本**: 最新 main 分支
