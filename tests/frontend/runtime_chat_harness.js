#!/usr/bin/env node
/**
 * WebUI 运行时聊天前端的行为测试 harness。
 *
 * 目的：替代原先「读 runtime.js 源码文本 + assert 子串」的变更检测器写法
 * （见 tests/test_webui_runtime_chat_frontend.py 的历史说明与
 * tests/test_source_assertion_budget.py 的预算棘轮）。
 *
 * 做法：用 jsdom 载入真实模板 index.html，按模板顺序 eval 真实依赖 JS，
 * 再 eval runtime.js；然后通过受控的 window.fetch 喂入会话/历史/作业事件载荷，
 * 用真实 DOM 事件驱动交互，最后 dump 出可断言的状态快照。
 *
 * 用法（由 Python 侧调用）：
 *   node tests/frontend/runtime_chat_harness.js --scenario <name> --root <repo>
 * 输出：单行 JSON 到 stdout（含 ok/error 与快照数据），供 Python 断言。
 */

"use strict";

const fs = require("node:fs");
const path = require("node:path");

const SCENARIO_FLAG = "--scenario";
const ROOT_FLAG = "--root";

// runtime.js 的 appendChatMessage 生成 `div.runtime-chat-item <role>`，
// 角色取自 class 列表（bot / user）。
const CHAT_ITEM_SELECTOR = ".runtime-chat-item";
const CHAT_ITEM_CLASSES = ["bot", "user"];

function parseChatRoles(window) {
    const roles = [];
    for (const el of window.document.querySelectorAll(CHAT_ITEM_SELECTOR)) {
        const classes = String(el.className || "").split(/\s+/);
        const role = CHAT_ITEM_CLASSES.find((name) => classes.includes(name)) || "";
        roles.push({ el, role });
    }
    return roles;
}

function chatLog(window) {
    return window.document.getElementById("runtimeChatLog");
}

/** 节点内所有正文块（timeline 会替换掉初始的单个 .runtime-chat-content）。 */
function contentTexts(el) {
    return Array.from(el.querySelectorAll(".runtime-chat-content")).map((node) =>
        (node.innerText || node.textContent || "").trim(),
    );
}

function toolBlockSnapshots(el) {
    return Array.from(el.querySelectorAll(".runtime-tool-block")).map((node) => ({
        classes: node.className || "",
        text: (node.innerText || node.textContent || "").trim(),
        open: node.hasAttribute("open"),
    }));
}

/** 收集聊天区所有消息节点的可断言快照。 */
function chatNodes(window) {
    return parseChatRoles(window).map(({ el, role }) => {
        const stageEl = el.querySelector(".runtime-chat-stage");
        const contents = contentTexts(el);
        const tools = toolBlockSnapshots(el);
        return {
            role,
            // 整节点文本含“AI/You”标签与按钮文案；断言正文请用 contentTexts
            text: (el.innerText || el.textContent || "").trim(),
            contentTexts: contents,
            contentText: contents.join("\n"),
            stageText: stageEl
                ? (stageEl.innerText || stageEl.textContent || "").trim()
                : "",
            // 由 setChatStage 直接写自 payload.elapsed_ms，不含本地流逝时间，
            // 因此适合做稳定断言（stageText 里的计数会随时间变化）
            stageBaseMs: stageEl ? stageEl.dataset.stageBaseMs || "" : "",
            stageIsFinal: stageEl
                ? stageEl.classList.contains("is-final")
                : null,
            stageHidden: stageEl
                ? stageEl.hasAttribute("hidden") ||
                  stageEl.getAttribute("aria-hidden") === "true"
                : null,
            classes: el.className || "",
            messageId: el.dataset ? el.dataset.messageId || "" : "",
            jobId: el.dataset ? el.dataset.jobId || "" : "",
            toolBlocks: tools,
        };
    });
}

/** 取 POST 到指定路径的请求体（解析为对象；解析失败返回 null）。 */
function requestBody(env, pathFragment) {
    for (const entry of env.requestDetails) {
        if (!entry.url.includes(pathFragment)) continue;
        const body = entry.options.body;
        if (typeof body !== "string") continue;
        try {
            return JSON.parse(body);
        } catch (_error) {
            return null;
        }
    }
    return null;
}

function parseArgs(argv) {
    const args = { scenario: "", root: "" };
    for (let i = 0; i < argv.length; i += 1) {
        if (argv[i] === SCENARIO_FLAG) args.scenario = argv[i + 1] || "";
        if (argv[i] === ROOT_FLAG) args.root = argv[i + 1] || "";
    }
    return args;
}

function resolveRoot(explicit) {
    if (explicit) return path.resolve(explicit);
    let dir = __dirname;
    for (let i = 0; i < 6; i += 1) {
        if (fs.existsSync(path.join(dir, "src/Undefined/webui/static/js/runtime.js"))) {
            return dir;
        }
        dir = path.dirname(dir);
    }
    throw new Error("找不到仓库根（缺少 src/Undefined/webui/static/js/runtime.js）");
}

/** 让出一轮宏任务 + 全部微任务，使 runtime.js 的 promise 链推进。 */
function tick(times = 8) {
    return new Promise((resolve) => {
        let remaining = times;
        const step = () => {
            remaining -= 1;
            if (remaining <= 0) resolve();
            else setTimeout(step, 0);
        };
        setTimeout(step, 0);
    });
}

/**
 * 再等一小段真实时间。
 *
 * runtime.js 的作业事件是「解析响应 → 应用事件 → 重排下一次轮询」的链，
 * 只靠宏任务让位不足以跑完，会给不出可断言的 DOM。
 */
function settle(ms = 40) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * 建立运行环境：真实模板 + 真实依赖 JS + 受控 fetch。
 *
 * fetch 的路由用「子串匹配 → 响应」表描述，命中第一个匹配项；
 * 未命中的请求**直接抛错**：静默返回 200 {} 会让 fixture 的路由写错时用例
 * 「通过」但什么都没测（错误信息里带上已声明的 match，方便定位）。
 *
 * @param {string} root 仓库根（`--root`）
 * @param {object} [options]
 * @param {Record<string, string>} [options.storage] 载入产品脚本前写入的
 *     localStorage 条目，用于模拟「刷新后恢复偏好」这类跨会话状态。
 * @param {boolean} [options.authenticated] 初始登录态。多数场景不需要，
 *     但 `state.authenticated` 为假时 runtime.js 会直接跳过 tab 激活等逻辑。
 */
function createEnv(root, options = {}) {
    const jsdom = require("jsdom");
    const { JSDOM } = jsdom;

    const staticDir = path.join(root, "src/Undefined/webui/static/js");
    const templatePath = path.join(root, "src/Undefined/webui/templates/index.html");
    const html = fs.readFileSync(templatePath, "utf8");
    const dom = new JSDOM(html, {
        url: "http://localhost/",
        runScripts: "outside-only",
        pretendToBeVisual: true,
    });
    const { window } = dom;

    // jsdom 未实现的浏览器 API：补最小桩，避免加载期直接抛错
    const scrollActivity = { calls: 0 };
    window.Element.prototype.scrollTo = function scrollTo() {
        scrollActivity.calls += 1;
    };
    window.Element.prototype.scrollIntoView = function scrollIntoView() {
        scrollActivity.calls += 1;
    };
    // 记录 scrollTop 被写入的次数（滚动到底通常直接赋值）
    const scrollTopWrites = { count: 0 };
    for (const proto of [window.Element.prototype, window.HTMLElement.prototype]) {
        const descriptor = Object.getOwnPropertyDescriptor(proto, "scrollTop");
        if (!descriptor || !descriptor.set) continue;
        Object.defineProperty(proto, "scrollTop", {
            get: descriptor.get,
            set(value) {
                scrollTopWrites.count += 1;
                return descriptor.set.call(this, value);
            },
            configurable: true,
        });
    }
    window.scrollTo = function scrollTo() {};
    if (!window.matchMedia) {
        window.matchMedia = () => ({
            matches: false,
            addEventListener() {},
            removeEventListener() {},
            addListener() {},
            removeListener() {},
        });
    }
    class NoopObserver {
        observe() {}
        unobserve() {}
        disconnect() {}
    }
    window.IntersectionObserver = window.IntersectionObserver || NoopObserver;
    window.ResizeObserver = window.ResizeObserver || NoopObserver;
    window.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 0);
    window.cancelAnimationFrame = (id) => clearTimeout(id);
    // jsdom 不实现 Element.innerText（返回 undefined），而 runtime.js 多处依赖它
    // 读取纯文本（例如引用内容提取会因此拿到空串）。用 textContent 近似替代；
    // 断言文本时仍优先用 textContent，避免把这个垫片当成被测行为。
    if (!Object.getOwnPropertyDescriptor(window.HTMLElement.prototype, "innerText")) {
        Object.defineProperty(window.HTMLElement.prototype, "innerText", {
            get() {
                return this.textContent;
            },
            configurable: true,
        });
    }
    // jsdom 没有 CSS.escape；runtime.js 用它拼属性选择器
    if (!window.CSS) window.CSS = {};
    if (!window.CSS.escape) {
        window.CSS.escape = (value) =>
            String(value).replace(/[^a-zA-Z0-9_\u00a0-\uffff-]/g, (ch) => `\\${ch}`);
    }
    window.localStorage.setItem("webui.locale", "zh-CN");
    Object.entries(options.storage || {}).forEach(([key, value]) => {
        window.localStorage.setItem(key, String(value));
    });

    // 事件流传输的绊线：产品若要退回 SSE，只能通过 EventSource 建立长连接，
    // 而 EventSource 不经过 window.fetch，因此不会出现在 requests 里。
    // jsdom 本身不实现 EventSource，这里装一个只计数的替身，让「不得退回 SSE」
    // 成为可观测的负向断言（而不是断言 accept 头——产品从不设置 Accept，
    // `assert not accept.startswith("text/event-stream")` 是恒真的）。
    const eventSourceConstructions = { count: 0 };
    window.EventSource = class HarnessEventSource {
        constructor(url) {
            eventSourceConstructions.count += 1;
            this.url = String(url);
        }
        close() {}
        addEventListener() {}
        removeEventListener() {}
    };

    const requests = [];
    const requestDetails = [];
    let routes = [];
    let fetchImpl = async (url, options) => {
        requests.push(String(url));
        requestDetails.push({ url: String(url), options: options || {} });
        return response(200, {});
    };
    window.fetch = (url, options) => fetchImpl(String(url), options);

    function response(status, payload) {
        return {
            ok: status >= 200 && status < 300,
            status,
            json: async () => payload,
            text: async () => JSON.stringify(payload),
            headers: { get: () => null },
        };
    }

    function setRoutes(next) {
        // 最长 match 优先：事件 URL（.../chat/jobs/<id>/events）也包含 "/chat/jobs"，
        // 若按声明顺序匹配会被通用路由抢先命中。
        routes = (next || [])
            .slice()
            .sort((a, b) => String(b.match).length - String(a.match).length);
        requests.length = 0;
        fetchImpl = async (url, options) => {
            requests.push(String(url));
            requestDetails.push({ url: String(url), options: options || {} });
            for (const route of routes) {
                if (url.includes(route.match)) {
                    const reply =
                        typeof route.reply === "function"
                            ? route.reply(url, options)
                            : route.reply;
                    if (reply === undefined || reply === null) break;
                    return response(reply.status || 200, reply.body || {});
                }
            }
            // 未命中即报错：以前这里静默返回 200 {}，于是 fixture 里的 match
            // 一旦与产品真实 URL 不一致（例如写 "/chat/commands" 而产品请求
            // "/api/runtime/commands?scope=webui"），用例会「通过」但什么都没测。
            throw new Error(
                `harness 未匹配到路由：${url}\n已声明的 match：` +
                    routes.map((route) => route.match).join(" | "),
            );
        };
    }

    // 浏览器里多个 <script> 共享同一个全局词法环境（`const state` 对后续脚本可见）。
    // window.eval 每次调用都会新建词法作用域，因此必须把所有脚本拼成一次 eval。
    // 顺序与 templates/index.html 的 <script> 顺序一致；vendor 库用仓库内的真实文件，
    // 否则 Markdown/代码高亮路径会被替换成桩，测不到真实渲染。
    const vendorDir = path.join(staticDir, "vendor");
    const deps = [
        path.join(vendorDir, "marked.min.js"),
        path.join(vendorDir, "highlight.min.js"),
        ...["i18n.js", "state.js", "ui.js", "api.js", "auth.js", "bot.js"].map((name) =>
            path.join(staticDir, name),
        ),
        path.join(staticDir, "runtime.js"),
    ];
    // harness 专用垫片：产品脚本里 `const state = {...}` 属于这次 eval 的词法作用域，
    // 后续 window.eval 看不到它。只有拼在同一次 eval 里才能改 `state.authenticated`
    // 这类模块内状态（tab 激活、抽屉等交互的前提条件）。
    const bootstrap = `
;(function () {
    window.__harness = window.__harness || {};
    window.__harness.setAuthenticated = function (value) {
        state.authenticated = !!value;
    };
})();`;
    window.eval(
        deps.map((file) => fs.readFileSync(file, "utf8")).join("\n;\n") +
            "\n;\n" +
            bootstrap,
    );
    if (options.authenticated) window.__harness.setAuthenticated(true);

    return {
        dom,
        root,
        window,
        requests,
        requestDetails,
        setRoutes,
        scrollActivity,
        scrollTopWrites,
        eventSourceConstructions,
        /**
         * 按需加载额外的 WebUI 脚本（普通 script 语义，模块自带 window 导出）。
         *
         * 基础依赖链在 createEnv 里就已经 eval 过，这里只用于「只有部分场景需要」
         * 的模块（工作流图/检查器、微信等），避免影响现有场景的加载结果。
         * 这些模块是 IIFE + `window.X = {...}` 导出，因此可以逐个 eval。
         */
        loadScripts(names) {
            for (const name of names) {
                const file = path.join(staticDir, name);
                window.eval(fs.readFileSync(file, "utf8"));
            }
        },
    };
}

// --------------------------------------------------------------------------- //
// DOM 观测
// --------------------------------------------------------------------------- //

function botNodes(window) {
    return chatNodes(window).filter((node) => node.role === "bot");
}

function textOf(window, id) {
    const el = window.document.getElementById(id);
    if (!el) return null;
    return (el.innerText || el.textContent || "").trim();
}

// --------------------------------------------------------------------------- //
// 场景
// --------------------------------------------------------------------------- //

const SCENARIOS = {};

/**
 * 发送一条消息 → 喂入 message 事件 → 断言最终消息复用同一个节点。
 *
 * 对应原 test_webchat_frontend_reuses_job_message_for_final_message 想守的行为：
 * 「message」事件必须复用 streaming 占位节点，而不是再 append 一条机器人消息。
 */
SCENARIOS.message_reuses_streaming_node = async (env) => {
    const { window, setRoutes } = env;
    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [{ id: "conv-1", title: "t" }],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            match: "/chat/history",
            reply: { body: { items: [], has_more: false, next_before: null } },
        },
        {
            match: "/chat/jobs",
            reply: { body: { job_id: "job-1", conversation_id: "conv-1" } },
        },
        {
            match: "/jobs/job-1/events",
            reply: {
                body: {
                    events: [
                        { seq: 1, event: "message", payload: { content: "你好" } },
                        { seq: 2, event: "message", payload: { content: "你好世界" } },
                        {
                            seq: 3,
                            event: "done",
                            payload: { duration_ms: 1200 },
                        },
                    ],
                    job: { job_id: "job-1", status: "done", last_seq: 3 },
                },
            },
        },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();
    window.RuntimeController.loadChatHistory(true).catch(() => {});
    await tick();

    const input = window.document.getElementById("runtimeChatInput");
    input.value = "hi";
    await window.eval("window.__sendPromise = window.RuntimeController ? null : null");
    // 通过真实按钮点击驱动，等价于用户操作
    const button = window.document.getElementById("btnRuntimeChatSend");
    button.click();
    await tick(4);
    await settle(400);

    const bots = botNodes(window);
    return {
        botMessageCount: bots.length,
        botTexts: bots.map((node) => node.text),
        allNodes: chatNodes(window),
        requests: env.requests.slice(),
    };
};

/**
 * 工具生命周期事件：tool_start / tool_end 应产生工具块并带上状态与时长。
 *
 * 对应原 test_webchat_frontend_handles_tool_lifecycle_and_webchat_hints。
 */
SCENARIOS.tool_lifecycle_renders_blocks = async (env) => {
    const { window, setRoutes } = env;
    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [{ id: "conv-1", title: "t" }],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            match: "/chat/history",
            reply: { body: { items: [], has_more: false, next_before: null } },
        },
        {
            match: "/chat/jobs",
            reply: { body: { job_id: "job-2", conversation_id: "conv-1" } },
        },
        {
            match: "/jobs/job-2/events",
            reply: {
                body: {
                    events: [
                        {
                            seq: 1,
                            event: "tool_start",
                            payload: {
                                call_id: "call-1",
                                name: "group.get_member_info",
                                args: { brief: true },
                            },
                        },
                        {
                            seq: 2,
                            event: "tool_end",
                            payload: {
                                call_id: "call-1",
                                name: "group.get_member_info",
                                duration_ms: 42,
                                result_preview: "张三",
                                // 真实后端只发 done/error（api/routes/chat.py 的
                                // _normalize_webchat_output），不发 "ok"
                                ok: true,
                                status: "done",
                            },
                        },
                        { seq: 3, event: "done", payload: { duration_ms: 900 } },
                    ],
                    job: { job_id: "job-2", status: "done", last_seq: 3 },
                },
            },
        },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();
    window.RuntimeController.loadChatHistory(true).catch(() => {});
    await tick();

    window.document.getElementById("runtimeChatInput").value = "look up";
    window.document.getElementById("btnRuntimeChatSend").click();
    await tick(4);
    await settle(400);

    const log = chatLog(window);
    const blocks = log ? Array.from(log.querySelectorAll(".runtime-tool-block")) : [];
    return {
        toolBlockCount: blocks.length,
        toolCallIds: blocks.map((el) => el.getAttribute("data-tool-call-id") || ""),
        toolTexts: blocks.map((el) => (el.innerText || el.textContent || "").trim()),
        allNodes: chatNodes(window),
        requests: env.requests.slice(),
    };
};

/**
 * stage 事件应渲染成实时的阶段提示。
 *
 * 对应原 test_webchat_frontend_renders_live_stage_after_ai_label。
 */
SCENARIOS.stage_event_renders_live_stage = async (env) => {
    const { window, setRoutes } = env;
    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [{ id: "conv-1", title: "t" }],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            match: "/chat/history",
            reply: { body: { items: [], has_more: false, next_before: null } },
        },
        {
            match: "/chat/jobs",
            reply: { body: { job_id: "job-3", conversation_id: "conv-1" } },
        },
        {
            match: "/jobs/job-3/events",
            reply: {
                body: {
                    events: [
                        {
                            seq: 1,
                            event: "stage",
                            payload: {
                                stage: "waiting_model",
                                elapsed_ms: 500,
                            },
                        },
                    ],
                    job: { job_id: "job-3", status: "running", last_seq: 1 },
                },
            },
        },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();
    window.RuntimeController.loadChatHistory(true).catch(() => {});
    await tick();

    window.document.getElementById("runtimeChatInput").value = "hello";
    window.document.getElementById("btnRuntimeChatSend").click();
    await tick(4);
    await settle(400);

    const log = chatLog(window);
    const stages = log
        ? Array.from(log.querySelectorAll(".runtime-chat-stage"))
        : [];
    return {
        stageNodeCount: stages.length,
        stageTexts: stages.map((el) => (el.innerText || el.textContent || "").trim()),
        allNodes: chatNodes(window),
        requests: env.requests.slice(),
    };
};

/**
 * 发送消息必须把 conversation_id 带进作业请求，并在事件轮询里带上同一会话。
 *
 * 对应原 test_webchat_frontend_sends_conversation_id_with_history_and_jobs。
 */
SCENARIOS.requests_carry_conversation_id = async (env) => {
    const { window, setRoutes } = env;
    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [{ id: "conv-9", title: "t" }],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            match: "/chat/history",
            reply: { body: { items: [], has_more: false, next_before: null } },
        },
        {
            match: "/chat/jobs",
            reply: { body: { job_id: "job-9", conversation_id: "conv-9" } },
        },
        {
            match: "/jobs/job-9/events",
            reply: {
                body: {
                    events: [{ seq: 1, event: "done", payload: { duration_ms: 10 } }],
                    job: { job_id: "job-9", status: "done", last_seq: 1 },
                },
            },
        },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();
    window.RuntimeController.loadChatHistory(true).catch(() => {});
    await tick();

    window.document.getElementById("runtimeChatInput").value = "hi";
    window.document.getElementById("btnRuntimeChatSend").click();
    await tick(4);
    await settle(400);

    return {
        requests: env.requests.slice(),
        requestDetails: env.requestDetails.map((entry) => ({
            url: entry.url,
            accept: String(
                (entry.options.headers || {}).Accept ||
                    (entry.options.headers || {}).accept ||
                    "",
            ),
        })),
        createJobBody: requestBody(env, "/chat/jobs"),
        // 事件消费必须走 fetch + JSON 轮询：一旦退回 SSE（EventSource 长连接），
        // 它不会出现在 requests 里，只能靠这个绊线观察到。
        eventSourceConstructions: env.eventSourceConstructions.count,
    };
};

/**
 * done 事件之后，工具块应保留最终时长而不是被清空。
 *
 * 对应原 test_webchat_frontend_keeps_final_duration_after_done。
 */
SCENARIOS.keeps_duration_after_done = async (env) => {
    const { window, setRoutes } = env;
    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [{ id: "conv-1", title: "t" }],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            match: "/chat/history",
            reply: { body: { items: [], has_more: false, next_before: null } },
        },
        {
            match: "/chat/jobs",
            reply: { body: { job_id: "job-4", conversation_id: "conv-1" } },
        },
        {
            match: "/jobs/job-4/events",
            reply: {
                body: {
                    events: [
                        {
                            seq: 1,
                            event: "tool_start",
                            payload: { call_id: "call-1", name: "render.markdown" },
                        },
                        {
                            seq: 2,
                            event: "tool_end",
                            payload: {
                                call_id: "call-1",
                                name: "render.markdown",
                                duration_ms: 2500,
                                ok: true,
                                status: "done",
                            },
                        },
                        { seq: 3, event: "done", payload: { duration_ms: 3000 } },
                    ],
                    job: { job_id: "job-4", status: "done", last_seq: 3 },
                },
            },
        },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();
    window.RuntimeController.loadChatHistory(true).catch(() => {});
    await tick();

    window.document.getElementById("runtimeChatInput").value = "render";
    window.document.getElementById("btnRuntimeChatSend").click();
    await tick(4);
    await settle(400);

    const log = chatLog(window);
    const blocks = log ? Array.from(log.querySelectorAll(".runtime-tool-block")) : [];
    return {
        toolBlockCount: blocks.length,
        toolTexts: blocks.map((el) => (el.innerText || el.textContent || "").trim()),
        allNodes: chatNodes(window),
        requests: env.requests.slice(),
    };
};

/**
 * 别的会话的作业事件不得落到当前会话的聊天区。
 *
 * 这对应 runtime.js 里唯一的两道跨会话守卫（applyChatEvent 的
 * eventForCurrentConversation 过滤 + applyChatEventsPayload 的归属判断），
 * 旧断言守的正是它，但迁移后一直没人覆盖——变异掉守卫也能全绿。
 */
SCENARIOS.foreign_conversation_events_are_ignored = async (env) => {
    const { window, setRoutes } = env;
    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [{ id: "conv-mine", title: "t" }],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            match: "/chat/history",
            reply: { body: { items: [], has_more: false, next_before: null } },
        },
        {
            match: "/chat/jobs",
            reply: { body: { job_id: "job-mine", conversation_id: "conv-mine" } },
        },
        {
            match: "/jobs/job-mine/events",
            reply: {
                body: {
                    events: [
                        {
                            seq: 1,
                            event: "message",
                            payload: {
                                content: "INTRUDER",
                                conversation_id: "conv-other",
                            },
                        },
                        {
                            seq: 2,
                            event: "message",
                            payload: {
                                content: "MINE",
                                conversation_id: "conv-mine",
                            },
                        },
                    ],
                    job: { job_id: "job-mine", status: "running", last_seq: 2 },
                },
            },
        },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();
    window.RuntimeController.loadChatHistory(true).catch(() => {});
    await tick();

    window.document.getElementById("runtimeChatInput").value = "hi";
    window.document.getElementById("btnRuntimeChatSend").click();
    await tick(4);
    await settle(400);

    const log = chatLog(window);
    return {
        allNodes: chatNodes(window),
        logText: log ? (log.innerText || "").trim() : "",
        requests: env.requests.slice(),
    };
};

/**
 * done 事件应把最终耗时写进阶段元素（final 态），而不是丢掉。
 *
 * 旧断言守的是 runtime.js 的 finalizeActiveChatMessage，迁移后一直没覆盖。
 */
SCENARIOS.done_event_keeps_final_duration = async (env) => {
    const { window, setRoutes } = env;
    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [{ id: "conv-1", title: "t" }],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            match: "/chat/history",
            reply: { body: { items: [], has_more: false, next_before: null } },
        },
        {
            match: "/chat/jobs",
            reply: { body: { job_id: "job-done", conversation_id: "conv-1" } },
        },
        {
            match: "/jobs/job-done/events",
            reply: {
                body: {
                    events: [
                        {
                            seq: 1,
                            event: "stage",
                            payload: { stage: "waiting_model", elapsed_ms: 100 },
                        },
                        {
                            seq: 2,
                            event: "message",
                            payload: { content: "answer" },
                        },
                        { seq: 3, event: "done", payload: { duration_ms: 3000 } },
                    ],
                    job: {
                        job_id: "job-done",
                        status: "done",
                        last_seq: 3,
                        duration_ms: 3000,
                    },
                },
            },
        },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();
    window.RuntimeController.loadChatHistory(true).catch(() => {});
    await tick();

    window.document.getElementById("runtimeChatInput").value = "hi";
    window.document.getElementById("btnRuntimeChatSend").click();
    await tick(4);
    await settle(400);

    return { allNodes: chatNodes(window), requests: env.requests.slice() };
};

/**
 * agent 生命周期事件应渲染成 agent 块（旧断言里的 agent_start/agent_end 分支）。
 */
SCENARIOS.agent_lifecycle_renders_agent_block = async (env) => {
    const { window, setRoutes } = env;
    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [{ id: "conv-1", title: "t" }],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            match: "/chat/history",
            reply: { body: { items: [], has_more: false, next_before: null } },
        },
        {
            match: "/chat/jobs",
            reply: { body: { job_id: "job-agent", conversation_id: "conv-1" } },
        },
        {
            match: "/jobs/job-agent/events",
            reply: {
                body: {
                    events: [
                        {
                            seq: 1,
                            event: "agent_start",
                            payload: { call_id: "agent-1", name: "web_agent" },
                        },
                        {
                            seq: 2,
                            event: "agent_end",
                            payload: {
                                call_id: "agent-1",
                                name: "web_agent",
                                ok: true,
                                status: "done",
                                duration_ms: 1500,
                            },
                        },
                        { seq: 3, event: "done", payload: { duration_ms: 2000 } },
                    ],
                    job: { job_id: "job-agent", status: "done", last_seq: 3 },
                },
            },
        },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();
    window.RuntimeController.loadChatHistory(true).catch(() => {});
    await tick();

    window.document.getElementById("runtimeChatInput").value = "search";
    window.document.getElementById("btnRuntimeChatSend").click();
    await tick(4);
    await settle(400);

    return { allNodes: chatNodes(window), requests: env.requests.slice() };
};

/**
 * Markdown / HTML 渲染必须被消毒：真实喂入 XSS 载荷再检查 DOM。
 *
 * 原断言全是「源码里必须出现 createSafeMarkedRenderer / SAFE_HTML_TAGS /
 * name.startsWith("on")」这类子串匹配——重构即红、真正的 XSS 回归却测不出来。
 * 这里改为把载荷渲染出来，直接看落到 DOM 里的是什么。
 */
SCENARIOS.markdown_sanitizes_unsafe_content = async (env) => {
    const { window, setRoutes } = env;
    const payload = [
        "普通文本",
        "",
        "<script>window.__XSS__ = 1;<\/script>",
        '<img src="x" onerror="window.__XSS__ = 2">',
        '<a href="javascript:window.__XSS__=3">危险链接</a>',
        '<a href="https://example.com/page">安全链接</a>',
        '<a href="https://example.com/rel">外链</a>',
        "",
        "![预览图](https://example.com/img.png)",
    ].join("\n");

    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [{ id: "conv-1", title: "t" }],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            match: "/chat/history",
            reply: { body: { items: [], has_more: false, next_before: null } },
        },
        { match: "/chat/jobs", reply: { body: { job_id: "job-xss" } } },
        {
            match: "/jobs/job-xss/events",
            reply: {
                body: {
                    events: [
                        { seq: 1, event: "message", payload: { content: payload } },
                        { seq: 2, event: "done", payload: { duration_ms: 100 } },
                    ],
                    job: { job_id: "job-xss", status: "done", last_seq: 2 },
                },
            },
        },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();
    window.RuntimeController.loadChatHistory(true).catch(() => {});
    await tick();

    window.document.getElementById("runtimeChatInput").value = "hi";
    window.document.getElementById("btnRuntimeChatSend").click();
    await tick(4);
    await settle(400);

    const log = chatLog(window);
    const anchors = log ? Array.from(log.querySelectorAll("a")) : [];
    const images = log ? Array.from(log.querySelectorAll("img")) : [];
    return {
        // 注意：harness 用 runScripts: "outside-only"，注入的 <script> 永远不会执行，
        // 所以「window.__XSS__ 是否被写入」恒为 undefined——那不是能分辨好坏的信号，
        // 真正的信号是下面这些 DOM 事实（script 标签数、内联事件属性、javascript: href）。
        scriptTags: log ? log.querySelectorAll("script").length : -1,
        inlineHandlerAttrs: log
            ? Array.from(log.querySelectorAll("*")).reduce((count, el) => {
                  const hits = Array.from(el.attributes || []).filter((attr) =>
                      attr.name.toLowerCase().startsWith("on"),
                  );
                  return count + hits.length;
              }, 0)
            : -1,
        anchors: anchors.map((a) => ({
            href: a.getAttribute("href") || "",
            rel: a.getAttribute("rel") || "",
        })),
        images: images.map((img) => ({
            src: img.getAttribute("src") || "",
            loading: img.getAttribute("loading") || "",
        })),
        // chatImageMarkup 产出的可点击预览图（data-chat-image-preview="1"）
        interactiveImages: log
            ? log.querySelectorAll("[data-chat-image-preview]").length
            : -1,
        allNodes: chatNodes(window),
    };
};

/**
 * 自动滚动开关：切换后偏好必须落到 localStorage，并在重载时读回。
 *
 * 原断言是「源码里要有 CHAT_AUTO_SCROLL_STORAGE_KEY / setChatAutoScroll(...) /
 * if (!runtimeState.chatAutoScroll) return」这类子串。
 *
 * 注意：**没有**断言「关掉开关后不再滚动」——jsdom 里多条渲染路径都会触发
 * scrollTo/scrollTop 写入，实测开关前后的调用次数只差 3 次（16 vs 13），
 * 达不到可依赖的信号强度。与其写一条看着在测、实际会漏报的断言，不如只验证
 * 确定性可达的部分（偏好持久化与读回）。
 */
SCENARIOS.auto_scroll_toggle_controls_scrolling = async (env) => {
    const { window, setRoutes } = env;
    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [{ id: "conv-1", title: "t" }],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            match: "/chat/history",
            reply: { body: { items: [], has_more: false, next_before: null } },
        },
        { match: "/chat/jobs", reply: { body: { job_id: "job-scroll" } } },
        {
            match: "/jobs/job-scroll/events",
            reply: {
                body: {
                    events: [
                        { seq: 1, event: "message", payload: { content: "one" } },
                        { seq: 2, event: "done", payload: { duration_ms: 50 } },
                    ],
                    job: { job_id: "job-scroll", status: "done", last_seq: 2 },
                },
            },
        },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();
    window.RuntimeController.loadChatHistory(true).catch(() => {});
    await tick();

    const toggle = window.document.getElementById("runtimeChatAutoScroll");
    // 场景 A：开关保持默认（开）-> 发消息应产生滚动活动
    env.scrollActivity.calls = 0;
    env.scrollTopWrites.count = 0;
    window.document.getElementById("runtimeChatInput").value = "hi";
    window.document.getElementById("btnRuntimeChatSend").click();
    await tick(4);
    await settle(400);
    const enabledScrollTo = env.scrollActivity.calls;

    // 场景 B：关掉开关后重置计数再发一条
    const toggleExists = !!toggle;
    if (toggle) {
        toggle.checked = false;
        toggle.dispatchEvent(new window.Event("change", { bubbles: true }));
    }
    await tick();
    env.scrollActivity.calls = 0;
    env.scrollTopWrites.count = 0;
    window.document.getElementById("runtimeChatInput").value = "again";
    window.document.getElementById("btnRuntimeChatSend").click();
    await tick(4);
    await settle(400);
    const disabledScrollTo = env.scrollActivity.calls;

    const storedPreference = window.localStorage.getItem(
        "undefined_webchat_auto_scroll",
    );

    // 模拟刷新：真的重建一次环境（新的 JSDOM + 重新 eval 产品脚本 + init），
    // 并把上一次运行时写进 localStorage 的值原样带过去。
    // 只对同一个 key 再 getItem 一次等于复读 storedPreference，证明不了任何事；
    // 重建后读的是产品自己恢复出来的开关状态（readChatAutoScrollPreference）。
    const reborn = createEnv(env.root, {
        storage: { undefined_webchat_auto_scroll: String(storedPreference) },
    });
    reborn.window.eval("window.RuntimeController.init()");
    await tick(2);
    const rebornToggle = reborn.window.document.getElementById(
        "runtimeChatAutoScroll",
    );

    return {
        toggleExists,
        toggleCheckedAfterChange: toggle ? toggle.checked : null,
        storedPreference,
        // 刷新后应由产品自己从 localStorage 恢复成关闭态
        reloadedToggleChecked: rebornToggle ? rebornToggle.checked : null,
        // 仅作参考打印，不断言（见场景注释）
        scrollCallsEnabled: enabledScrollTo,
        scrollCallsDisabled: disabledScrollTo,
        allNodes: chatNodes(window),
    };
};

/**
 * 工具块的摘要结构：名称 → 耗时 → 状态 → 类型，且状态文案与耗时都在。
 *
 * 原断言靠「在源码里找 runtime-tool-name / runtime-tool-duration / 比较它们在
 * 字符串里的下标顺序」来表达这件事——渲染顺序回归时完全测不到。这里改为解析
 * 真实 DOM 的顺序与文本。
 */
SCENARIOS.tool_summary_order_and_duration = async (env) => {
    const { window, setRoutes } = env;
    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [{ id: "conv-1", title: "t" }],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            match: "/chat/history",
            reply: { body: { items: [], has_more: false, next_before: null } },
        },
        { match: "/chat/jobs", reply: { body: { job_id: "job-sum" } } },
        {
            match: "/jobs/job-sum/events",
            reply: {
                body: {
                    events: [
                        {
                            seq: 1,
                            event: "tool_start",
                            payload: {
                                call_id: "call-1",
                                name: "render.markdown",
                                args: { markdown: "# hi" },
                            },
                        },
                        {
                            seq: 2,
                            event: "tool_end",
                            payload: {
                                call_id: "call-1",
                                name: "render.markdown",
                                ok: true,
                                status: "done",
                                duration_ms: 1234,
                                result_preview: "RESULT_PREVIEW_TOKEN",
                            },
                        },
                        { seq: 3, event: "done", payload: { duration_ms: 1500 } },
                    ],
                    job: { job_id: "job-sum", status: "done", last_seq: 3 },
                },
            },
        },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();
    window.RuntimeController.loadChatHistory(true).catch(() => {});
    await tick();

    window.document.getElementById("runtimeChatInput").value = "render";
    window.document.getElementById("btnRuntimeChatSend").click();
    await tick(4);
    await settle(400);

    const log = chatLog(window);
    const summaries = log
        ? Array.from(log.querySelectorAll(".runtime-tool-block summary")).map((el) => ({
              // 按 DOM 顺序取出摘要内部部件
              parts: Array.from(el.children).map((child) => child.className || ""),
              text: (el.innerText || el.textContent || "").trim(),
          }))
        : [];
    const block = log ? log.querySelector(".runtime-tool-block") : null;
    return {
        summaryCount: summaries.length,
        summaryParts: summaries.map((entry) => entry.parts),
        summaryText: summaries.map((entry) => entry.text),
        blockText: block ? (block.innerText || block.textContent || "").trim() : "",
        // 结构化预览（args / result）是否渲染
        previewBlocks: log
            ? log.querySelectorAll(".runtime-tool-block pre, .runtime-tool-block code")
                  .length
            : -1,
        allNodes: chatNodes(window),
    };
};

/**
 * 从后端历史恢复时间线：工具块、嵌套结构、agent 摘要与最终耗时。
 *
 * 覆盖原先靠源码子串表达的若干契约：历史里的工具块要能重建（不依赖流式状态）、
 * 聊天区是事件时间线、后端历史时长写入 final 阶段、agent 摘要不产生时间线噪音。
 */
SCENARIOS.history_timeline_restores_tool_blocks = async (env) => {
    const { window, setRoutes } = env;
    const historyItem = {
        role: "bot",
        content: "最终答复正文",
        webchat: {
            duration_ms: 4200,
            events: [
                {
                    seq: 1,
                    event: "tool_start",
                    payload: {
                        call_id: "call-outer",
                        name: "web_agent",
                        is_agent: true,
                    },
                },
                {
                    seq: 2,
                    event: "tool_end",
                    payload: {
                        call_id: "call-outer",
                        name: "web_agent",
                        ok: true,
                        status: "done",
                        duration_ms: 3000,
                        result_preview: "AGENT_PREVIEW",
                    },
                },
                {
                    seq: 3,
                    event: "tool_start",
                    payload: { call_id: "call-inner", name: "render.markdown" },
                },
                {
                    seq: 4,
                    event: "tool_end",
                    payload: {
                        call_id: "call-inner",
                        name: "render.markdown",
                        ok: true,
                        status: "done",
                        duration_ms: 800,
                        result_preview: "INNER_PREVIEW",
                    },
                },
                {
                    seq: 5,
                    event: "message",
                    payload: { content: "时间线内的中间消息" },
                },
            ],
        },
    };

    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [{ id: "conv-hist", title: "t" }],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            match: "/chat/history",
            reply: {
                body: { items: [historyItem], has_more: false, next_before: null },
            },
        },
        {
            match: "/chat/jobs/active",
            reply: { body: { active_job: null } },
        },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();
    window.RuntimeController.loadChatHistory(true).catch(() => {});
    await tick(4);
    await settle(300);

    const log = chatLog(window);
    const blocks = log
        ? Array.from(log.querySelectorAll(".runtime-tool-block")).map((el) => ({
              classes: el.className || "",
              text: (el.innerText || el.textContent || "").trim(),
              // 嵌套：块内部是否还有子块
              nested: el.querySelectorAll(".runtime-tool-block").length,
          }))
        : [];
    return {
        allNodes: chatNodes(window),
        toolBlockCount: blocks.length,
        toolBlocks: blocks,
        timelineContainers: log
            ? log.querySelectorAll(".runtime-chat-timeline").length
            : -1,
        logText: log ? (log.innerText || "").trim() : "",
    };
};

/**
 * 富内容渲染：Markdown 引用折叠块、代码高亮、独立 HTML（内联片段与整篇文档）、
 * 工具结构化预览、引用条（markdown 引用前缀）、以及附件图片去重。
 *
 * 覆盖原先十几条靠源码子串表达的渲染契约；这里把内容真渲染出来，按 DOM 结构断言。
 */
SCENARIOS.rich_content_rendering = async (env) => {
    const { window, setRoutes } = env;
    const content = [
        "> 被引用的历史消息内容",
        "> 引用第二行",
        "",
        "普通段落带 `inline code`。",
        "",
        "```js",
        "const answered = 42;",
        "```",
        "",
        "<div class=\"standalone-html\">独立 HTML 片段</div>",
        "",
        "<attachment uid=\"pic_dup\"/>",
    ].join("\n");
    // 整条消息就是一份独立 HTML 文档：走 looksLikeStandaloneHtml 的
    // sanitizeHtmlSnippet 分支（而不是 marked）。两者对纯标签的渲染结果一样，
    // 只有「标签之间夹着的裸文本」能区分：snippet 分支保留为裸文本节点，
    // marked 分支会把空行后的文本包成 <p>。
    const standaloneDocument = [
        '<div title="standalone-document">',
        "",
        "STANDALONE_DOC_BODY",
        "",
        "</div>",
    ].join("\n");

    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [{ id: "conv-rich", title: "t" }],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            match: "/chat/history",
            reply: { body: { items: [], has_more: false, next_before: null } },
        },
        { match: "/chat/jobs", reply: { body: { job_id: "job-rich" } } },
        {
            match: "/jobs/job-rich/events",
            reply: {
                body: {
                    events: [
                        {
                            seq: 1,
                            event: "tool_start",
                            payload: {
                                call_id: "call-rich",
                                name: "render.markdown",
                                args: {
                                    markdown: "# title",
                                    options: { theme: "dark" },
                                },
                            },
                        },
                        {
                            seq: 2,
                            event: "tool_end",
                            payload: {
                                call_id: "call-rich",
                                name: "render.markdown",
                                ok: true,
                                status: "done",
                                duration_ms: 100,
                                result_preview: "PREVIEW_JSON",
                            },
                        },
                        {
                            seq: 3,
                            event: "message",
                            payload: {
                                content,
                                attachments: [
                                    {
                                        uid: "pic_dup",
                                        kind: "image",
                                        media_type: "image/png",
                                        display_name: "dup.png",
                                        url: "https://example.com/dup.png",
                                    },
                                ],
                            },
                        },
                        {
                            seq: 4,
                            event: "message",
                            payload: { content: standaloneDocument },
                        },
                        { seq: 5, event: "done", payload: { duration_ms: 200 } },
                    ],
                    job: { job_id: "job-rich", status: "done", last_seq: 5 },
                },
            },
        },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();
    window.RuntimeController.loadChatHistory(true).catch(() => {});
    await tick();

    // 引用条：点一次「引用」按钮，把消息内容挂成引用
    window.document.getElementById("runtimeChatInput").value = "hi";
    window.document.getElementById("btnRuntimeChatSend").click();
    await tick(4);
    await settle(400);

    const log = chatLog(window);
    const blocks = log ? log.querySelectorAll(".runtime-tool-block") : [];
    return {
        allNodes: chatNodes(window),
        // Markdown 引用块
        blockquotes: log ? log.querySelectorAll("blockquote").length : -1,
        // 代码高亮：hljs 会给代码块加 class
        highlighted: log
            ? log.querySelectorAll("pre code.hljs, pre code[class*='language-']").length
            : -1,
        preCount: log ? log.querySelectorAll("pre").length : -1,
        // 独立 HTML（嵌在 Markdown 里的那段）：必须是**真实元素**，而不是
        // 「文本里恰好也有这几个字」——消毒只改结构，不能把标签变成字面量文本
        // （后者用 innerText.includes 断言照样通过，因为转义后的源码里也有这串字）。
        standaloneInlineElement: (() => {
            if (!log) return null;
            const target = Array.from(log.querySelectorAll("*")).find(
                (el) =>
                    el.children.length === 0 &&
                    (el.textContent || "").trim() === "独立 HTML 片段",
            );
            if (!target) return null;
            return {
                tag: target.tagName.toLowerCase(),
                insidePre: !!target.closest("pre"),
                insideCode: !!target.closest("code"),
            };
        })(),
        // 整条消息是一份独立 HTML 文档：必须走 sanitizeHtmlSnippet 分支，
        // 标签之间的裸文本不能被 marked 包成 <p>。
        standaloneDocument: (() => {
            if (!log) return null;
            const block = Array.from(
                log.querySelectorAll(".runtime-chat-content"),
            ).find((el) => (el.textContent || "").includes("STANDALONE_DOC_BODY"));
            if (!block) return null;
            return {
                hasMarkerElement: !!block.querySelector(
                    '[title="standalone-document"]',
                ),
                paragraphCount: block.querySelectorAll("p").length,
                text: (block.textContent || "").trim(),
            };
        })(),
        // 工具结构化预览（args/result）
        toolPreviewBlocks: blocks.length
            ? blocks[0].querySelectorAll("pre, code").length
            : -1,
        toolBlockText: blocks.length
            ? (blocks[0].innerText || blocks[0].textContent || "").trim()
            : "",
        // 附件图片去重：pic_dup 只应出现一次。
        // 注意渲染层会把 URL 重写成 /api/runtime/chat/attachments/<uid>/preview，
        // 因此按 uid 匹配而不是原始文件名。
        attachmentImages: log
            ? Array.from(log.querySelectorAll("img")).filter(
                  (img) =>
                      (img.getAttribute("src") || "").includes("pic_dup") ||
                      (img.getAttribute("alt") || "").includes("dup.png"),
              ).length
            : -1,
        attachmentPreviewSrcs: log
            ? Array.from(log.querySelectorAll("img"))
                  .map((img) => img.getAttribute("src") || "")
                  .filter((src) => src.includes("pic_dup"))
            : [],
        logHtmlLength: log ? (log.innerHTML || "").length : -1,
    };
};

/**
 * 取消与重试控件：运行中显示取消按钮并真的发出取消请求；重试按钮复用上一条用户消息。
 *
 * 原断言全是「源码里要有 cancelActiveChatJob / data-cancel-job / showToast(...)」
 * 之类的子串匹配；这里改为点按钮、看请求与 DOM。
 */
SCENARIOS.cancel_and_retry_controls = async (env) => {
    const { window, setRoutes } = env;
    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [{ id: "conv-1", title: "t" }],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            match: "/chat/history",
            reply: { body: { items: [], has_more: false, next_before: null } },
        },
        { match: "/chat/jobs", reply: { body: { job_id: "job-cancel" } } },
        { match: "/cancel", reply: { body: { ok: true } } },
        {
            match: "/jobs/job-cancel/events",
            reply: {
                body: {
                    events: [
                        {
                            seq: 1,
                            event: "message",
                            payload: { content: "partial" },
                        },
                    ],
                    // 保持 running，让取消按钮处于可见状态
                    job: { job_id: "job-cancel", status: "running", last_seq: 1 },
                },
            },
        },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();
    window.RuntimeController.loadChatHistory(true).catch(() => {});
    await tick();

    window.document.getElementById("runtimeChatInput").value = "please do it";
    window.document.getElementById("btnRuntimeChatSend").click();
    await tick(4);
    await settle(400);

    const log = chatLog(window);
    const cancelButtons = log
        ? Array.from(log.querySelectorAll("[data-cancel-job]"))
        : [];
    // 可见性用 hidden 属性判断：jsdom 没有布局，offsetParent 恒为 null
    const visibleCancel = cancelButtons.filter((btn) => !btn.hidden).length;
    // 先取快照：点击取消后按钮可能被移除
    const cancelJobId = cancelButtons.length
        ? cancelButtons[0].getAttribute("data-cancel-job") || ""
        : "";
    const cancelDisabledBeforeClick = cancelButtons.length
        ? cancelButtons[0].disabled
        : null;

    // 点取消
    if (cancelButtons.length) {
        cancelButtons[0].click();
        await tick(4);
        await settle(300);
    }

    const retryButtons = log
        ? Array.from(log.querySelectorAll("[data-retry-message]"))
        : [];

    return {
        cancelButtonCount: cancelButtons.length,
        visibleCancelCount: visibleCancel,
        cancelJobId,
        cancelDisabledBeforeClick,
        retryButtonCount: retryButtons.length,
        // 重试内容挂在所属消息节点的 data-retry-content 上
        retryContent: (() => {
            const item = log ? log.querySelector("[data-retry-content]") : null;
            return item ? item.getAttribute("data-retry-content") || "" : "";
        })(),
        cancelRequested: env.requestDetails.some((entry) =>
            entry.url.includes("/cancel"),
        ),
        requests: env.requests.slice(),
        allNodes: chatNodes(window),
    };
};

/**
 * UI 控件：会话侧栏抽屉、斜杠命令面板、图片查看器。
 *
 * 原断言是「模板里要有 runtimeChatConversations / btnRuntimeChatNew /
 * 源码里要有 openChatCommandPalette / openChatImageViewer」这类子串匹配；
 * 这里真的点开、真的触发输入，再断言可观测状态。
 */
SCENARIOS.ui_controls = async (env) => {
    const { window, setRoutes } = env;
    const content = "看图 ![图片](https://example.com/pic.png)";

    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [
                        { id: "conv-a", title: "会话甲" },
                        { id: "conv-b", title: "会话乙" },
                    ],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            // 产品请求的是 /api/runtime/commands?scope=webui（runtime.js）；
            // 以前这里写 "/chat/commands"，永远匹配不上，命令面板因此恒为空态，
            // 还被误判成「jsdom 限制」登记成了豁免。
            match: "/commands?scope=webui",
            reply: {
                body: {
                    commands: [
                        { name: "help", description: "显示帮助" },
                        { name: "stats", description: "统计信息" },
                    ],
                },
            },
        },
        {
            match: "/chat/history",
            reply: {
                body: {
                    items: [{ role: "bot", content }],
                    has_more: false,
                    next_before: null,
                },
            },
        },
        { match: "/chat/jobs/active", reply: { body: { active_job: null } } },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();
    window.RuntimeController.loadChatHistory(true).catch(() => {});
    await tick(4);
    await settle(200);

    const doc = window.document;
    // 抽屉的开关状态挂在 `.runtime-chat-sidebar` 上（setChatConversationDrawerOpen），
    // 不是挂在面板 `#runtimeChatConversationDrawerPanel` 上——早先读错了元素，
    // 于是无论怎么点都是 false。
    const drawer = doc.querySelector(".runtime-chat-sidebar");
    const toggle = doc.getElementById("runtimeChatConversationDrawerToggle");
    const drawerOpenBefore = drawer ? drawer.classList.contains("is-open") : null;
    // 抽屉开关按视口宽度门控（canToggleChatConversationDrawer: innerWidth <= 768），
    // jsdom 默认 1024，因此以前点开关是空转、drawerOpenAfter 恒 false。
    // 显式把视口压到窄屏，点完再还原，避免影响后面的命令面板与图片查看器。
    const viewportDescriptor = Object.getOwnPropertyDescriptor(
        window,
        "innerWidth",
    );
    Object.defineProperty(window, "innerWidth", {
        value: 480,
        writable: true,
        configurable: true,
    });
    if (toggle) {
        toggle.click();
        await tick(2);
    }
    const drawerOpenAfter = drawer ? drawer.classList.contains("is-open") : null;
    const drawerAriaExpandedAfter = toggle
        ? toggle.getAttribute("aria-expanded")
        : null;
    if (toggle) {
        toggle.click();
        await tick(2);
    }
    const drawerOpenAfterSecondToggle = drawer
        ? drawer.classList.contains("is-open")
        : null;
    if (viewportDescriptor) {
        Object.defineProperty(window, "innerWidth", viewportDescriptor);
    }

    // 会话列表渲染
    const conversationItems = doc.querySelectorAll(
        "#runtimeChatConversations [data-conversation-id], #runtimeChatConversations .runtime-chat-conversation",
    ).length;

    // 命令面板：输入 "/" 触发
    const input = doc.getElementById("runtimeChatInput");
    input.value = "/";
    input.dispatchEvent(new window.Event("input", { bubbles: true }));
    await tick(4);
    await settle(250);
    const palette = doc.getElementById("runtimeChatCommandPalette");
    const paletteHidden = palette ? palette.hasAttribute("hidden") : null;
    const paletteItems = palette
        ? palette.querySelectorAll("[data-command-name], li, button").length
        : -1;
    const paletteText = palette
        ? (palette.innerText || palette.textContent || "").trim()
        : "";

    // 图片查看器：点可点击预览图
    const previewImg = doc.querySelector("[data-chat-image-preview]");
    const viewer = doc.getElementById("runtimeChatImageViewer");
    const viewerHiddenBefore = viewer ? viewer.hasAttribute("hidden") : null;
    if (previewImg) {
        previewImg.click();
        await tick(2);
    }
    const viewerHiddenAfter = viewer ? viewer.hasAttribute("hidden") : null;
    const viewerImageSrc = (() => {
        const img = doc.getElementById("runtimeChatImageViewerImage");
        return img ? img.getAttribute("src") || "" : "";
    })();

    // 关闭查看器
    const closeBtn = doc.getElementById("btnRuntimeChatImageViewerClose");
    if (closeBtn) {
        closeBtn.click();
        await tick(2);
    }
    const viewerHiddenClosed = viewer ? viewer.hasAttribute("hidden") : null;

    return {
        drawerOpenBefore,
        drawerOpenAfter,
        drawerAriaExpandedAfter,
        drawerOpenAfterSecondToggle,
        conversationItems,
        paletteHidden,
        paletteItems,
        paletteText,
        previewImageCount: doc.querySelectorAll("[data-chat-image-preview]").length,
        viewerHiddenBefore,
        viewerHiddenAfter,
        viewerImageSrc,
        viewerHiddenClosed,
    };
};

/**
 * 附件粘贴与引用条：把文件粘贴进输入框要挂成待发附件；点机器人消息的「引用」
 * 要把该消息挂成待发引用，并在**发送时**把它前置成 markdown 引用块。
 *
 * 原断言是「源码里要有 addEventListener("paste" / chatReferences.push /
 * data-quote-message」之类的子串匹配。
 *
 * 注意：引用不进输入框（产品把它做成独立的引用条），所以只读 `input.value`
 * 是读不到任何东西的；真正的契约发生在发送时拼出的 outbound message 上。
 */
SCENARIOS.paste_files_and_quote_reference = async (env) => {
    const { window, setRoutes } = env;
    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [{ id: "conv-1", title: "t" }],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            match: "/chat/history",
            reply: {
                body: {
                    items: [{ role: "bot", content: "机器人历史消息" }],
                    has_more: false,
                    next_before: null,
                },
            },
        },
        { match: "/chat/jobs/active", reply: { body: { active_job: null } } },
        { match: "/chat/jobs", reply: { body: { job_id: "job-quote" } } },
        {
            match: "/jobs/job-quote/events",
            reply: {
                body: {
                    events: [],
                    job: { job_id: "job-quote", status: "running", last_seq: 0 },
                },
            },
        },
        {
            match: "/chat/files",
            reply: { body: { id: "file_pasted", uid: "file_pasted", name: "pasted.txt" } },
        },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();
    window.RuntimeController.loadChatHistory(true).catch(() => {});
    await tick(4);
    await settle(200);

    const doc = window.document;
    const input = doc.getElementById("runtimeChatInput");

    // 1) 粘贴一个文件
    const file = new window.File(["pasted content"], "pasted.txt", {
        type: "text/plain",
    });
    const pasteEvent = new window.Event("paste", { bubbles: true, cancelable: true });
    pasteEvent.clipboardData = {
        files: [file],
        items: [{ kind: "file", type: "text/plain", getAsFile: () => file }],
        types: ["Files"],
    };
    input.dispatchEvent(pasteEvent);
    await tick(4);
    await settle(200);

    const attachmentsContainer = doc.getElementById("runtimeChatAttachments");
    const pendingAttachments = attachmentsContainer
        ? attachmentsContainer.querySelectorAll("*").length
        : -1;
    const attachmentsText = attachmentsContainer
        ? (attachmentsContainer.innerText || attachmentsContainer.textContent || "").trim()
        : "";

    // 2) 引用一条机器人消息
    const quoteButton = doc.querySelector("[data-quote-message]");
    const quoteExists = !!quoteButton;
    if (quoteButton) {
        quoteButton.click();
        await tick(4);
    }
    const referencesContainer = doc.getElementById("runtimeChatReferences");
    const referencesCount = referencesContainer
        ? referencesContainer.querySelectorAll("*").length
        : -1;
    const referencesText = referencesContainer
        ? (referencesContainer.innerText || referencesContainer.textContent || "").trim()
        : "";

    // 3) 发送：引用必须在发送时被前置成 markdown 引用块。
    // （引用不写进输入框——产品把它做成独立的引用条，所以这里没有 input.value 可断言。）
    input.value = "请继续";
    doc.getElementById("btnRuntimeChatSend").click();
    await tick(4);
    await settle(300);

    const createJobBody = requestBody(env, "/chat/jobs");
    return {
        pendingAttachments,
        attachmentsText,
        quoteExists,
        referencesCount,
        referencesText,
        outboundMessage:
            createJobBody && typeof createJobBody.message === "string"
                ? createJobBody.message
                : "",
        requests: env.requests.slice(),
    };
};

/**
 * 增量轮询与刷新后恢复活跃作业。
 *
 * 原断言是「源码里要有 pollChatJob / after: String(runtimeState.lastEventSeq) /
 * attachChatJob(jobId, runtimeState.lastEventSeq)」这类子串；这里改为观察真实请求：
 * 第二轮的 after 必须推进，且刷新时能按会话找回活跃作业并继续轮询。
 */
SCENARIOS.incremental_polling_and_resume = async (env) => {
    const { window, setRoutes } = env;
    let eventRound = 0;

    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [{ id: "conv-poll", title: "t" }],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            match: "/chat/history",
            reply: { body: { items: [], has_more: false, next_before: null } },
        },
        {
            match: "/chat/jobs/active",
            reply: {
                body: {
                    active_job: {
                        job_id: "job-poll",
                        status: "running",
                        last_seq: 5,
                        conversation_id: "conv-poll",
                    },
                },
            },
        },
        {
            match: "/chat/jobs",
            reply: { body: { job_id: "job-poll", conversation_id: "conv-poll" } },
        },
        {
            match: "/jobs/job-poll/events",
            reply: () => {
                eventRound += 1;
                if (eventRound === 1) {
                    return {
                        body: {
                            events: [
                                {
                                    seq: 1,
                                    event: "message",
                                    payload: { content: "first" },
                                },
                            ],
                            job: { job_id: "job-poll", status: "running", last_seq: 1 },
                        },
                    };
                }
                if (eventRound === 2) {
                    return {
                        body: {
                            events: [
                                {
                                    seq: 2,
                                    event: "message",
                                    payload: { content: "second" },
                                },
                            ],
                            job: { job_id: "job-poll", status: "running", last_seq: 2 },
                        },
                    };
                }
                return {
                    body: {
                        events: [],
                        job: { job_id: "job-poll", status: "done", last_seq: 3 },
                    },
                };
            },
        },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();
    window.RuntimeController.loadChatHistory(true).catch(() => {});
    await tick();
    // 发起作业才会启动事件轮询（恢复逻辑只对已有本地 job 生效）
    window.document.getElementById("runtimeChatInput").value = "go";
    window.document.getElementById("btnRuntimeChatSend").click();
    await tick(4);
    await settle(1400);

    const eventUrls = env.requests.filter((url) => url.includes("/events"));
    const afterValues = eventUrls.map((url) => {
        const match = /[?&]after=([^&]*)/.exec(url);
        return match ? match[1] : "";
    });

    return {
        eventRequestCount: eventUrls.length,
        afterValues,
        activeJobQueried: env.requests.some((url) => url.includes("/chat/jobs/active")),
        allNodes: chatNodes(window),
    };
};

/**
 * HTML 运行器：点代码块的「运行 HTML」应打开预览面板，并把带 CSP 的文档注入沙箱 iframe。
 *
 * 原断言是「源码里要有 allow-forms / allow-modals / buildHtmlRunnerDocument /
 * injectHtmlRunnerSecurity」之类的子串；这里看真实的沙箱属性与注入结果。
 */
SCENARIOS.html_runner_uses_sandboxed_preview = async (env) => {
    const { window, setRoutes } = env;
    const content = ["```html", "<button>hi</button>", "```"].join("\n");

    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [{ id: "conv-1", title: "t" }],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            match: "/chat/history",
            reply: {
                body: {
                    items: [{ role: "bot", content }],
                    has_more: false,
                    next_before: null,
                },
            },
        },
        { match: "/chat/jobs/active", reply: { body: { active_job: null } } },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();
    window.RuntimeController.loadChatHistory(true).catch(() => {});
    await tick(4);
    await settle(200);

    const doc = window.document;
    const runButton = doc.querySelector("[data-code-run-html]");
    const runner = doc.getElementById("runtimeHtmlRunner");
    const frame = doc.getElementById("runtimeHtmlRunnerFrame");
    const hiddenBefore = runner ? runner.hasAttribute("hidden") : null;

    if (runButton) {
        runButton.click();
        await tick(4);
        await settle(200);
    }

    const srcdoc = frame ? frame.getAttribute("srcdoc") || "" : "";
    // nonce 必须是挂在真实 <script> 标签上的：只搜 /nonce-[A-Za-z0-9]+/ 会被
    // 注入文档里 CSP meta 自身的 `script-src 'nonce-…'` 满足，脚本标签整个被删掉
    // 也照样「通过」。这里解析出脚本标签上的 nonce，并校验它与 CSP 里声明的一致
    // （两者不一致等于没有保护）。
    const scriptNonce = /<script nonce="([^"]+)">/.exec(srcdoc);
    const cspNonce = /'nonce-([^']+)'/.exec(srcdoc);
    return {
        runButtonExists: !!runButton,
        sandbox: frame ? frame.getAttribute("sandbox") || "" : "",
        hiddenBefore,
        hiddenAfter: runner ? runner.hasAttribute("hidden") : null,
        srcdocHasCsp: srcdoc.includes("Content-Security-Policy"),
        srcdocScriptNonce: scriptNonce ? scriptNonce[1] : "",
        srcdocCspNonce: cspNonce ? cspNonce[1] : "",
        srcdocNonceMatchesCsp: !!(
            scriptNonce &&
            cspNonce &&
            scriptNonce[1] === cspNonce[1]
        ),
        srcdocLength: srcdoc.length,
        // 预览文档必须自包含：不允许外链脚本
        srcdocHasInlineSource: srcdoc.includes("<button>hi</button>"),
    };
};

/**
 * 工具块的两次关键行为：
 * 1) 快照内容不变时不得重绘（DOM 节点保持同一引用，避免闪烁与丢失展开态）；
 * 2) 工具结束后经过最小可见时间要自动折叠（去掉 open 属性）。
 *
 * 原断言是「源码里要有 toolRenderSignature / durationBaseMs /
 * TOOL_AUTO_COLLAPSE_MIN_VISIBLE_MS」这类子串；这里直接观察节点身份与 open 状态。
 *
 * 去重必须**跨一次轮询**观察：轮询间隔 500ms，而每次轮询都会重绘工具块，
 * 所以「随手读两次」几乎必然落在同一轮之后，节点身份恒等，断言恒真。
 * 这里把两次读取安排在「第 2 轮响应到达前 / 第 2 轮响应应用后」——第 2 轮正是
 * 携带内容完全相同快照的那一轮，两次读取之间只有这一次轮询：
 *
 * - 读取点 A：第 2 轮请求进入路由（此时第 1 轮的 DOM 已应用、第 2 轮尚未应用）；
 * - 读取点 B：第 3 轮请求进入路由（此时第 2 轮已应用、第 3 轮尚未应用）。
 *
 * 两个读取点都在路由回调里同步完成，因此不存在「读的时候恰好还在重绘」的竞态。
 */
SCENARIOS.tool_snapshot_dedup_and_auto_collapse = async (env) => {
    const { window, setRoutes } = env;
    let round = 0;
    const snapshot = {
        call_id: "call-snap",
        name: "web_agent",
        args: { query: "same" },
        status: "running",
    };
    const log = chatLog(window);
    const currentToolBlock = () =>
        log ? log.querySelector(".runtime-tool-block") : null;
    let toolBlockBeforeDuplicatePoll = null;
    let toolBlockAfterDuplicatePoll = null;
    let openAfterSnapshot = null;
    let roundAtFirstRead = 0;
    let roundAtSecondRead = 0;

    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [{ id: "conv-1", title: "t" }],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            match: "/chat/history",
            reply: { body: { items: [], has_more: false, next_before: null } },
        },
        { match: "/chat/jobs", reply: { body: { job_id: "job-snap" } } },
        {
            match: "/jobs/job-snap/events",
            reply: () => {
                round += 1;
                if (round === 1) {
                    return {
                        body: {
                            events: [
                                {
                                    seq: 1,
                                    event: "tool_start",
                                    payload: { call_id: "call-snap", name: "web_agent" },
                                },
                            ],
                            job: {
                                job_id: "job-snap",
                                status: "running",
                                last_seq: 1,
                                current_tool_calls: [snapshot],
                            },
                        },
                    };
                }
                if (round === 2) {
                    // 内容完全相同的快照 -> 不应重绘。
                    // 读取点 A：第 1 轮的 DOM 已经应用，第 2 轮还没应用。
                    toolBlockBeforeDuplicatePoll = currentToolBlock();
                    openAfterSnapshot = toolBlockBeforeDuplicatePoll
                        ? toolBlockBeforeDuplicatePoll.hasAttribute("open")
                        : null;
                    roundAtFirstRead = round;
                    return {
                        body: {
                            events: [],
                            job: {
                                job_id: "job-snap",
                                status: "running",
                                last_seq: 1,
                                current_tool_calls: [snapshot],
                            },
                        },
                    };
                }
                if (round === 3) {
                    // 读取点 B：第 2 轮（内容相同的快照）已经应用，第 3 轮还没应用。
                    // 两次读取之间只隔着第 2 轮这一次轮询。
                    toolBlockAfterDuplicatePoll = currentToolBlock();
                    roundAtSecondRead = round;
                    // 标记为结束 -> 之后再等最小可见时间会折叠
                    return {
                        body: {
                            events: [
                                {
                                    seq: 2,
                                    event: "tool_end",
                                    payload: {
                                        call_id: "call-snap",
                                        name: "web_agent",
                                        ok: true,
                                        status: "done",
                                        duration_ms: 300,
                                    },
                                },
                            ],
                            job: { job_id: "job-snap", status: "running", last_seq: 2 },
                        },
                    };
                }
                return {
                    body: {
                        events: [],
                        job: {
                            job_id: "job-snap",
                            status: "done",
                            last_seq: 2,
                            duration_ms: 500,
                        },
                    },
                };
            },
        },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();
    window.RuntimeController.loadChatHistory(true).catch(() => {});
    await tick();

    window.document.getElementById("runtimeChatInput").value = "go";
    window.document.getElementById("btnRuntimeChatSend").click();

    // 让第 3 轮请求发出：它一定发生在第 2 轮响应被应用之后。
    // 按对象身份比较（不能用自定义属性做标记：重绘会让标记一起消失，无法区分原因）。
    for (let i = 0; i < 60 && round < 3; i += 1) {
        await settle(100);
    }
    const sameNodeReused =
        !!toolBlockBeforeDuplicatePoll &&
        toolBlockAfterDuplicatePoll === toolBlockBeforeDuplicatePoll;

    // 再等一轮让 tool_end 生效
    await settle(900);
    const afterEnd = currentToolBlock();
    const openAfterEnd = afterEnd ? afterEnd.hasAttribute("open") : null;

    // 自动折叠：再等超过 TOOL_AUTO_COLLAPSE_MIN_VISIBLE_MS(2000)
    await settle(2600);
    const afterCollapse = currentToolBlock();

    return {
        roundsServiced: round,
        toolBlockCount: log ? log.querySelectorAll(".runtime-tool-block").length : -1,
        openAfterSnapshot,
        roundAtFirstRead,
        roundAtSecondRead,
        // 两次读取之间经过的轮询次数：必须恰好 1，否则「节点身份不变」可能
        // 只是因为观测窗里根本没有轮询。
        pollsBetweenReads: roundAtSecondRead - roundAtFirstRead,
        sameNodeReused,
        openAfterEnd,
        openAfterCollapse: afterCollapse
            ? afterCollapse.hasAttribute("open")
            : null,
        classesAfterCollapse: afterCollapse ? afterCollapse.className || "" : "",
    };
};

// --------------------------------------------------------------------------- //

/**
 * 滚动行为三则（jsdom 没有布局，因此 scrollHeight 由测试桩控制）：
 * 1) tab 激活后强制滚到底；
 * 2) 发送消息后滚到底；
 * 3) 惰性加载更早历史时保持可视位置（补偿新增高度）。
 *
 * 原断言都是「源码里要有 forceScrollChatToBottomSoon / setTimeout(..., 80)」
 * 这类子串；这里观察真实的滚动调用与 scrollTop 结果。
 */
function _stubScrollHeight(env, initial) {
    const log = env.window.document.getElementById("runtimeChatLog");
    let height = initial;
    Object.defineProperty(log, "scrollHeight", {
        get: () => height,
        configurable: true,
    });
    env.scrollActivity.calls = 0;
    env.scrollTopWrites.count = 0;
    return {
        get height() {
            return height;
        },
        set(next) {
            height = next;
        },
        element: log,
    };
}

SCENARIOS.scroll_behaviors = async (env) => {
    const { window, setRoutes } = env;
    const pageOne = [{ role: "bot", content: "最近的回复" }];
    const pageTwo = [{ role: "bot", content: "更早的回复" }];
    let eventRound = 0;

    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [{ id: "conv-scroll", title: "t" }],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            // 按游标决定返回哪一页：tab 激活也会触发一次历史加载，
            // 用「第几次调用」判断页码会被调用顺序带偏。
            match: "/chat/history",
            reply: (url) =>
                url.includes("before=cursor-1")
                    ? { body: { items: pageTwo, has_more: false, next_before: null } }
                    : {
                          body: {
                              items: pageOne,
                              has_more: true,
                              next_before: "cursor-1",
                          },
                      },
        },
        { match: "/chat/jobs/active", reply: { body: { active_job: null } } },
        { match: "/chat/jobs", reply: { body: { job_id: "job-scrollb" } } },
        {
            match: "/jobs/job-scrollb/events",
            reply: () => {
                eventRound += 1;
                if (eventRound === 1) {
                    return {
                        body: {
                            events: [
                                {
                                    seq: 1,
                                    event: "message",
                                    payload: { content: "reply" },
                                },
                            ],
                            job: {
                                job_id: "job-scrollb",
                                status: "running",
                                last_seq: 1,
                            },
                        },
                    };
                }
                // 尽快让作业结束：只要还在轮询，每一轮里的「滚到底」就会把
                // 顶部加载抑制窗口（900ms）不断续期，惰性加载永远进不去。
                return {
                    body: {
                        events: [],
                        job: {
                            job_id: "job-scrollb",
                            status: "done",
                            last_seq: 2,
                            duration_ms: 120,
                        },
                    },
                };
            },
        },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();

    // --- 1) tab 激活 ---
    // onTabActivated 有 `if (!state.authenticated) return` 前置守卫，不摆好登录态
    // 就点等于什么都没发生（这正是早先 tabActivationScrolls 恒 0 的原因）。
    window.__harness.setAuthenticated(true);
    // 先走一遍完整加载，让 chatHistoryLoaded 为真；之后再激活 tab 时
    // loadChatHistory 会早退回，唯一还会强制滚到底的就是 onTabActivated 自己，
    // 这样信号才归因明确。这里必须等过 forceScrollChatToBottomSoon 的 700ms 尾巴，
    // 否则第一次激活遗留的定时器会混进下一次计数。
    window.RuntimeController.onTabActivated("chat");
    await tick(4);
    await settle(1000);

    _stubScrollHeight(env, 1200);
    window.RuntimeController.onTabActivated("chat");
    await tick(4);
    await settle(900);
    const tabActivationScrolls = env.scrollActivity.calls;

    // --- 2) 发送消息 ---
    _stubScrollHeight(env, 1500);
    window.document.getElementById("runtimeChatInput").value = "hi";
    window.document.getElementById("btnRuntimeChatSend").click();
    await tick(4);
    await settle(400);
    const sendScrolls = env.scrollActivity.calls;

    // --- 3) 惰性加载：滚到顶部触发；高度增长后 scrollTop 应被补偿 ---
    // 作业结束后轮询停止（否则每轮的滚到底会不断续期顶部加载抑制窗口），
    // 再等过抑制窗口 CHAT_TOP_LOAD_SUPPRESS_MS = 900ms。
    await settle(1500);

    const meter3 = _stubScrollHeight(env, 2000);
    const previousTop = 0;
    meter3.element.scrollTop = previousTop;
    const growth = 800;
    meter3.element.addEventListener("scroll", () => {
        meter3.set(2000 + growth);
    });
    meter3.element.dispatchEvent(new window.Event("scroll", { bubbles: false }));
    await tick(4);
    await settle(400);

    const olderHistoryRequests = env.requests.filter((url) =>
        url.includes("before=cursor-1"),
    );

    return {
        tabActivationScrolls,
        sendScrolls,
        lazyLoadScrollTop: meter3.element.scrollTop,
        lazyLoadExpectedTop: previousTop + growth,
        lazyLoadHeight: meter3.height,
        olderHistoryRequestCount: olderHistoryRequests.length,
        allNodes: chatNodes(window),
    };
};

/**
 * 作业**持续运行**时用户往上翻历史。
 *
 * 这里针对两个各自独立、并已用变异测试确认的缺陷：
 *
 * 1. ``scrollChatToBottom()`` 只看 ``chatAutoScroll`` 偏好，不看用户当前位置：
 *    只要流式内容还在追加，每 500ms 一次的轮询就会把人从历史里拽回底部。
 * 2. 顶部加载抑制窗口（900ms）会被持续续期。续期路径是**内容变化**触发的
 *    ``scrollChatToBottomSoon()``（每轮 message 事件经 ``appendTimelineMessage``；
 *    ``upsertAgentStageBlock`` 在阶段签名变化时同理），而 ``loadOlderChatHistory``
 *    全文件只有 scroll 监听这一个调用点、也没有可点的兜底入口——窗口一旦不过期，
 *    用户就是**无声地翻不上去**。
 *
 * 两个断言分别对应这两点，各自都有能单独打红它的变异：去掉「钉住底部」的闸，
 * 用户上翻后仍会出现自动滚动；去掉「用户上翻即解除抑制」，则完全发不出翻页请求。
 */
SCENARIOS.scroll_while_streaming = async (env) => {
    const { window, setRoutes } = env;
    const pageOne = [{ role: "bot", content: "最近的回复" }];
    const pageTwo = [{ role: "bot", content: "更早的回复" }];
    let eventRound = 0;

    setRoutes([
        {
            match: "/chat/conversations",
            reply: {
                body: {
                    conversations: [{ id: "conv-stream", title: "t" }],
                    default_conversation_id: "webchat",
                    active_job: null,
                },
            },
        },
        {
            match: "/chat/history",
            reply: (url) =>
                url.includes("before=cursor-1")
                    ? { body: { items: pageTwo, has_more: false, next_before: null } }
                    : {
                          body: {
                              items: pageOne,
                              has_more: true,
                              next_before: "cursor-1",
                          },
                      },
        },
        { match: "/chat/jobs/active", reply: { body: { active_job: null } } },
        { match: "/chat/jobs", reply: { body: { job_id: "job-stream-scroll" } } },
        {
            match: "/jobs/job-stream-scroll/events",
            reply: () => {
                eventRound += 1;
                // 每一轮都有新内容：这既是真实的流式输出，也是「自动滚到底」
                // 真正会触发的路径（appendTimelineMessage -> scrollChatToBottomSoon），
                // 因此旧实现每 500ms 就会抢一次滚动位置并续期抑制窗口。
                return {
                    body: {
                        events: [
                            {
                                seq: eventRound,
                                event: "message",
                                payload: { content: `流式片段 ${eventRound}` },
                            },
                        ],
                        job: {
                            job_id: "job-stream-scroll",
                            status: "running",
                            last_seq: eventRound,
                        },
                    },
                };
            },
        },
    ]);

    window.eval("window.RuntimeController.init()");
    await tick();
    window.__harness.setAuthenticated(true);
    window.RuntimeController.onTabActivated("chat");
    await tick(4);
    await settle(1000);

    const meter = _stubScrollHeight(env, 3000);
    const log = meter.element;
    window.document.getElementById("runtimeChatInput").value = "hi";
    window.document.getElementById("btnRuntimeChatSend").click();
    await tick(4);
    await settle(600);

    // 用户此刻在底部：先用一次位于底部的滚动事件建立「上次位置」，
    // 这样后面的向上翻才判定得出来。
    log.scrollTop = 3000;
    log.dispatchEvent(new window.Event("scroll", { bubbles: false }));
    await tick(2);

    // 让作业多跑几轮：旧实现每一轮都会把抑制窗口续到 now+900ms。
    await settle(1200);
    env.scrollActivity.calls = 0;
    env.scrollTopWrites.count = 0;
    const requestsBeforeScroll = env.requests.length;
    const eventsRequests = env.requests.filter((url) =>
        url.includes("/jobs/job-stream-scroll/events"),
    ).length;

    // 作业仍在运行时，用户主动往上翻到顶部。
    log.scrollTop = 0;
    log.dispatchEvent(new window.Event("scroll", { bubbles: false }));
    await tick(4);
    await settle(500);

    return {
        eventsRequests,
        jobStillStreaming: eventsRequests >= 3,
        olderHistoryRequestsWhileStreaming: env.requests
            .slice(requestsBeforeScroll)
            .filter((url) => url.includes("before=cursor-1")).length,
        scrollCallsAfterUserScroll: env.scrollActivity.calls,
        scrollTopWritesAfterUserScroll: env.scrollTopWrites.count,
    };
};

/**
 * 工作流图的纯逻辑契约（不依赖 DOM 交互）。
 *
 * 原断言是对 workflow-graph.js / workflow-inspector.js 做源码子串匹配
 * （例如 `emptyTask` 函数体里必须出现 `consume_ai_loop: false`）。这里改为调用
 * 真实导出，断言**返回值**：新建工作流的默认值、克隆隔离、JSON 美化等。
 */
SCENARIOS.workflow_graph_defaults = async (env) => {
    env.loadScripts(["workflow-graph.js"]);
    const graph = env.window.WorkflowGraph;
    if (!graph) throw new Error("workflow-graph.js 未导出 WorkflowGraph");

    const task = graph.emptyTask();
    // 默认值必须是「不消费 / 不自动发送」，避免新建工作流意外拦截主 AI
    const defaults = {
        consumeAiLoop: task.consume_ai_loop,
        autoSendFinal: task.auto_send_final,
    };

    // clone 必须是深拷贝（改副本不得影响原对象）
    const copy = graph.clone(task);
    copy.consume_ai_loop = true;
    if (copy.consume_ai_loop === task.consume_ai_loop) {
        throw new Error("clone 不是深拷贝");
    }

    // 默认节点的结构
    const node = graph.defaultNode ? graph.defaultNode("start") : null;

    return {
        taskKeys: Object.keys(task).sort(),
        defaults,
        cloneIsolation: copy.consume_ai_loop !== task.consume_ai_loop,
        nodeType: node ? String(node.type || "") : "",
        paletteTypes: Array.isArray(graph.PALETTE_TYPES)
            ? graph.PALETTE_TYPES.length
            : -1,
        eventKinds: Array.isArray(graph.EVENT_KINDS)
            ? graph.EVENT_KINDS.length
            : -1,
        prettyJsonSample: graph.prettyJson({ b: 1, a: [1, 2] }),
    };
};

/**
 * 变量检查器：真实实例化 createInspector，断言它产出的 DOM 带哪些交互属性。
 *
 * 原断言是「inspector.js 里必须出现 data-extract-add / patch.extract_vars /
 * node.type === "llm.main"」这类子串——检查器不再渲染这些控件也测不到。
 */
SCENARIOS.workflow_inspector_extract_vars = async (env) => {
    env.loadScripts(["workflow-graph.js", "workflow-inspector.js"]);
    const graphApi = env.window.WorkflowGraph;
    const inspectorApi = env.window.WorkflowInspector;
    if (!graphApi || !inspectorApi) {
        throw new Error("工作流模块未导出");
    }

    // 造一个带 llm.main 节点的工作流并选中它
    const task = graphApi.emptyTask();
    const node = graphApi.defaultNode("llm.main");
    node.id = "llm1";
    task.nodes.push(node);
    const graph = graphApi.createGraph(task);
    // 选中该节点：createGraph 默认选中 start（方法是 selectNode）
    graph.selectNode("llm1");

    const root = env.window.document.createElement("div");
    env.window.document.body.appendChild(root);
    const inspector = inspectorApi.createInspector(
        root,
        graph,
        () => ({ tools: [], agents: [], toolsets: [] }),
    );
    if (inspector && typeof inspector.render === "function") {
        inspector.render();
    }

    const html = root.innerHTML || "";

    // 再给一个变量：此时应出现「移除」控件
    graph.updateNode("llm1", { extract_vars: ["foo"] });
    inspector.render();
    const htmlWithVar = root.innerHTML || "";

    // 分支节点的 case 编辑器（branch.if 才有 cases）
    const branchTask = graphApi.emptyTask();
    const branchNode = graphApi.defaultNode("branch.if");
    branchNode.id = "branch1";
    branchTask.nodes.push(branchNode);
    const branchGraph = graphApi.createGraph(branchTask);
    branchGraph.selectNode("branch1");
    const branchRoot = env.window.document.createElement("div");
    env.window.document.body.appendChild(branchRoot);
    const branchInspector = inspectorApi.createInspector(
        branchRoot,
        branchGraph,
        () => ({ tools: [], agents: [], toolsets: [] }),
    );
    if (branchInspector && typeof branchInspector.render === "function") {
        branchInspector.render();
    }
    const branchHtml = branchRoot.innerHTML || "";

    return {
        renderedLength: html.length,
        hasExtractAdd: html.includes("data-extract-add"),
        hasExtractRemove: html.includes("data-extract-remove"),
        hasExtractRemoveWithVar: htmlWithVar.includes("data-extract-remove"),
        hasCaseJson: branchHtml.includes("data-case-json"),
        selectedNodeRendered: html.includes("llm1"),
        nodeTypeInState: (() => {
            const state = graph.getState();
            const current = state.task.nodes.find((n) => n.id === state.selectedId);
            return current ? String(current.type || "") : "";
        })(),
        // 节点默认应带空的变量提取列表
        defaultExtractVars: Array.isArray(node.extract_vars)
            ? node.extract_vars.length
            : null,
        htmlExcerpt: html.slice(0, 200),
    };
};

/**
 * 工具参数的类型往返：number / boolean / object / null 必须原样保留。
 *
 * 原断言是「inspector.js 里要有 JSON.stringify(value) / JSON.parse(value)」这类
 * 子串；这里断言真实往返后的**类型**，以及编辑器是否渲染出 JSON 输入框。
 */
SCENARIOS.workflow_tool_args_json_round_trip = async (env) => {
    env.loadScripts(["workflow-graph.js", "workflow-inspector.js"]);
    const graphApi = env.window.WorkflowGraph;
    const inspectorApi = env.window.WorkflowInspector;

    const task = graphApi.emptyTask();
    const node = graphApi.defaultNode("tool");
    node.id = "tool1";
    node.args = { n: 1, b: true, s: "x", o: { k: 1 }, arr: [1, 2], z: null };
    task.nodes.push(node);

    // 经 createGraph 往返一次（load 会 clone）
    const graph = graphApi.createGraph(task);
    const roundTripped = graph.getState().task.nodes.find((n) => n.id === "tool1");
    const args = (roundTripped && roundTripped.args) || {};
    const typesPreserved =
        typeof args.n === "number" &&
        typeof args.b === "boolean" &&
        typeof args.s === "string" &&
        Array.isArray(args.arr) &&
        args.o !== null &&
        typeof args.o === "object";

    graph.selectNode("tool1");
    const root = env.window.document.createElement("div");
    env.window.document.body.appendChild(root);
    const inspector = inspectorApi.createInspector(root, graph, () => ({
        tools: [{ name: "demo.tool", description: "d" }],
        agents: [],
        toolsets: [],
    }));
    if (inspector && typeof inspector.render === "function") inspector.render();
    const html = root.innerHTML || "";

    return {
        typesPreserved,
        nullPreserved: Object.prototype.hasOwnProperty.call(args, "z") && args.z === null,
        argTypes: Object.fromEntries(
            Object.entries(args).map(([k, v]) => [k, Array.isArray(v) ? "array" : typeof v]),
        ),
        hasJsonPlaceholder: html.includes("JSON value"),
        renderedLength: html.length,
    };
};

async function main() {
    const args = parseArgs(process.argv.slice(2));
    if (!args.scenario) throw new Error("缺少 --scenario");
    const scenario = SCENARIOS[args.scenario];
    if (!scenario) {
        throw new Error(
            `未知场景 ${args.scenario}；可用：${Object.keys(SCENARIOS).sort().join(", ")}`,
        );
    }
    const root = resolveRoot(args.root);
    const env = createEnv(root);
    const result = await scenario(env);
    process.stdout.write(
        `${JSON.stringify({ ok: true, scenario: args.scenario, result })}\n`,
    );
    // runtime.js 的聊天轮询会不断重排 setTimeout，事件循环不会自己空下来，
    // 因此写完成结果后直接退出（结果已经 flush 到 stdout）。
    process.exit(0);
}

main().catch((error) => {
    process.stdout.write(
        `${JSON.stringify({
            ok: false,
            error: String((error && error.stack) || error),
        })}\n`,
    );
    process.exit(1);
});
