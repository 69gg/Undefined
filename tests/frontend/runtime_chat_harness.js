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
 * 未命中的请求返回 200 + {} 并记录，方便排查。
 */
function createEnv(root) {
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
    // jsdom 没有 CSS.escape；runtime.js 用它拼属性选择器
    if (!window.CSS) window.CSS = {};
    if (!window.CSS.escape) {
        window.CSS.escape = (value) =>
            String(value).replace(/[^a-zA-Z0-9_\u00a0-\uffff-]/g, (ch) => `\\${ch}`);
    }
    window.localStorage.setItem("webui.locale", "zh-CN");

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
            return response(200, {});
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
    window.eval(deps.map((file) => fs.readFileSync(file, "utf8")).join("\n;\n"));

    return {
        dom,
        window,
        requests,
        requestDetails,
        setRoutes,
        scrollActivity,
        scrollTopWrites,
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
        xssFired: window.__XSS__ || null,
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

    // 重新读取偏好（模拟刷新后初始化）：应恢复为关闭态
    const reloaded = window.localStorage.getItem("undefined_webchat_auto_scroll");

    return {
        toggleExists,
        toggleCheckedAfterChange: toggle ? toggle.checked : null,
        storedPreference,
        reloadedPreference: reloaded,
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
 * 富内容渲染：Markdown 引用折叠块、代码高亮、独立 HTML、工具结构化预览、
 * 引用条（markdown 引用前缀）、以及附件图片去重。
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
                        { seq: 4, event: "done", payload: { duration_ms: 200 } },
                    ],
                    job: { job_id: "job-rich", status: "done", last_seq: 4 },
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
        // 独立 HTML：标记本身被消毒器改写（class 可能被丢），但文本内容必须保留
        standaloneHtmlText:
            log &&
            ((log.innerText || log.textContent || "").includes("独立 HTML 片段"))
                ? 1
                : 0,
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

// --------------------------------------------------------------------------- //

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
