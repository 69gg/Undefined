"""Execute an automation DAG with variable interpolation."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Awaitable, Callable

from Undefined.automations.clock import clock_matches
from Undefined.automations.constants import (
    BRANCH_ELSE_CASE,
    DEFAULT_BLANK_LLM_MAX_ITERATIONS,
    DEFAULT_NODE_TIMEOUT_SECONDS,
    DEFAULT_WORKFLOW_TIMEOUT_SECONDS,
    LOOP_EXIT_KIND,
    LOOP_MAX_ITERATIONS,
    START_NODE_ID,
)
from Undefined.automations.logutil import preview_text
from Undefined.automations.match import AutomationEvent, match_condition_on_text
from Undefined.automations.template import (
    assign_node_output,
    render_template,
    render_value,
)

logger = logging.getLogger(__name__)

ExecuteTool = Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[Any]]
SubmitLLM = Callable[..., Awaitable[dict[str, Any]]]
SendMessage = Callable[[str], Awaitable[None]]
AskMain = Callable[[str, dict[str, Any]], Awaitable[str]]


class WorkflowError(RuntimeError):
    """Raised when a workflow node fails."""

    def __init__(self, message: str, *, node_id: str = "") -> None:
        super().__init__(message)
        self.node_id = node_id


def find_start_node(task: dict[str, Any]) -> dict[str, Any] | None:
    nodes = task.get("nodes")
    if not isinstance(nodes, list):
        return None
    for node in nodes:
        if isinstance(node, dict) and str(node.get("id") or "") == START_NODE_ID:
            return node
    return None


def start_kind(task: dict[str, Any]) -> str:
    start = find_start_node(task)
    if start is None:
        return ""
    return str(start.get("kind") or "").strip()


def _node_map(task: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for node in task.get("nodes") or []:
        if isinstance(node, dict) and node.get("id"):
            mapping[str(node["id"])] = node
    return mapping


def _loop_bodies(nodes: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    bodies: dict[str, set[str]] = {}
    for node_id, node in nodes.items():
        if str(node.get("type") or "") not in {"loop.times", "loop.each"}:
            continue
        body = node.get("body")
        if not isinstance(body, list):
            bodies[node_id] = set()
            continue
        bodies[node_id] = {str(item).strip() for item in body if str(item).strip()}
    return bodies


def _edges(task: dict[str, Any]) -> list[dict[str, Any]]:
    raw = task.get("edges")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _tool_function_name(schema: dict[str, Any]) -> str:
    function = schema.get("function")
    if isinstance(function, dict):
        return str(function.get("name") or "")
    return ""


def filter_openai_tools(
    all_tools: list[dict[str, Any]],
    *,
    tools: list[str] | None,
    toolsets: list[str] | None,
    agents: list[str] | None,
) -> list[dict[str, Any]]:
    allow_tools = {str(name).strip() for name in (tools or []) if str(name).strip()}
    allow_sets = {str(name).strip() for name in (toolsets or []) if str(name).strip()}
    allow_agents = {str(name).strip() for name in (agents or []) if str(name).strip()}
    if not allow_tools and not allow_sets and not allow_agents:
        return []
    selected: list[dict[str, Any]] = []
    for schema in all_tools:
        name = _tool_function_name(schema)
        internal = name.replace("-_-", ".")
        if internal in allow_tools or name in allow_tools:
            selected.append(schema)
            continue
        prefix = internal.split(".", 1)[0]
        if prefix in allow_sets:
            selected.append(schema)
            continue
        if internal in allow_agents or name in allow_agents:
            selected.append(schema)
    return selected


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except TypeError:
            return str(value)
    return str(value)


def _parse_each_source(raw: str) -> list[Any]:
    text = raw.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return list(parsed)
    except json.JSONDecodeError:
        pass
    return [line for line in text.splitlines() if line.strip()]


_OPTION_ID_RE = re.compile(r"[^A-Za-z0-9_]+")


def option_tool_name(option_id: str) -> str:
    cleaned = _OPTION_ID_RE.sub("_", str(option_id).strip()) or "option"
    return f"choose_{cleaned}"


class WorkflowRunner:
    """Run one automation graph to completion."""

    def __init__(
        self,
        *,
        execute_tool: ExecuteTool,
        ask_main: AskMain,
        submit_llm: SubmitLLM,
        send_message: SendMessage,
        get_openai_tools: Callable[[], list[dict[str, Any]]],
        agent_config: Any,
        tool_context: dict[str, Any],
        node_timeout_seconds: float = DEFAULT_NODE_TIMEOUT_SECONDS,
        workflow_timeout_seconds: float = DEFAULT_WORKFLOW_TIMEOUT_SECONDS,
        blank_llm_max_iterations: int = DEFAULT_BLANK_LLM_MAX_ITERATIONS,
        loop_max_iterations: int = LOOP_MAX_ITERATIONS,
    ) -> None:
        self.execute_tool = execute_tool
        self.ask_main = ask_main
        self.submit_llm = submit_llm
        self.send_message = send_message
        self.get_openai_tools = get_openai_tools
        self.agent_config = agent_config
        self.tool_context = tool_context
        self.node_timeout_seconds = node_timeout_seconds
        self.workflow_timeout_seconds = workflow_timeout_seconds
        self.blank_llm_max_iterations = blank_llm_max_iterations
        self.loop_max_iterations = max(
            1, min(int(loop_max_iterations), LOOP_MAX_ITERATIONS)
        )
        self._continue_on_tool_error = False

    def _task_id(self) -> str:
        return str(self.tool_context.get("scheduled_task_id") or "")

    async def run(
        self,
        task: dict[str, Any],
        *,
        event: AutomationEvent,
        pass_text: str,
        consume_mentions: tuple[str, ...],
        consume_stripped: str,
        mentions_all: tuple[str, ...],
    ) -> str:
        self._continue_on_tool_error = bool(task.get("compat_continue_on_tool_error"))
        nodes = task.get("nodes")
        edges = task.get("edges")
        logger.info(
            "[自动化] DAG 开始: id=%s name=%s nodes=%s edges=%s pass_len=%s mentions=%s channel=%s address=%s",
            self._task_id(),
            str(task.get("task_name") or ""),
            len(nodes) if isinstance(nodes, list) else 0,
            len(edges) if isinstance(edges, list) else 0,
            len(pass_text),
            ",".join(consume_mentions) or "-",
            event.channel,
            event.address,
        )
        variables: dict[str, Any] = {
            "trigger": {
                "text": pass_text,
                "text_original": event.text,
                "text_stripped": consume_stripped,
                "mentions": list(consume_mentions),
                "mentions_all": list(mentions_all),
                "channel": event.channel,
                "sender_id": event.sender_id,
                "nickname": event.nickname,
                "address": event.address,
                "group_id": event.group_id,
                "user_id": event.user_id,
                "time": datetime.now().isoformat(timespec="seconds"),
            },
            "nodes": {},
            "vars": {},
            "index": 0,
            "item": "",
        }
        emitted = False

        async def emit_if_needed(node: dict[str, Any], output: str) -> None:
            nonlocal emitted
            if bool(node.get("emit")) and output.strip():
                logger.info(
                    "[自动化] 节点出站: id=%s node=%s len=%s preview=%s",
                    self._task_id(),
                    node.get("id"),
                    len(output),
                    preview_text(output),
                )
                await self.send_message(output)
                emitted = True

        async def wrapped() -> str:
            last = await self._run_graph(
                task,
                variables=variables,
                emit_if_needed=emit_if_needed,
                include_bodies=False,
            )
            if not emitted and bool(task.get("auto_send_final", True)) and last.strip():
                logger.info(
                    "[自动化] 自动发送终态: id=%s len=%s preview=%s",
                    self._task_id(),
                    len(last),
                    preview_text(last),
                )
                await self.send_message(last)
            return last

        try:
            result = await asyncio.wait_for(
                wrapped(), timeout=self.workflow_timeout_seconds
            )
        except TimeoutError as exc:
            logger.error(
                "[自动化] 工作流超时: id=%s timeout=%.0fs",
                self._task_id(),
                self.workflow_timeout_seconds,
            )
            raise WorkflowError(
                f"workflow timeout after {self.workflow_timeout_seconds}s"
            ) from exc
        logger.info(
            "[自动化] DAG 结束: id=%s out_len=%s preview=%s",
            self._task_id(),
            len(result),
            preview_text(result),
        )
        return result

    async def _run_graph(
        self,
        task: dict[str, Any],
        *,
        variables: dict[str, Any],
        emit_if_needed: Callable[[dict[str, Any], str], Awaitable[None]],
        include_bodies: bool,
        only_ids: set[str] | None = None,
    ) -> str:
        nodes = _node_map(task)
        bodies = _loop_bodies(nodes)
        body_ids: set[str] = set()
        for members in bodies.values():
            body_ids.update(members)
        edges = _edges(task)
        if only_ids is not None:
            active_ids = set(only_ids)
        elif include_bodies:
            active_ids = set(nodes)
        else:
            active_ids = {node_id for node_id in nodes if node_id not in body_ids}

        completed: dict[str, str] = {}
        if START_NODE_ID in active_ids:
            completed[START_NODE_ID] = str(
                variables.get("trigger", {}).get("text") or ""
            )

        activated: set[tuple[str, str, str]] = set()

        def activate_from(source_id: str, case: str | None = None) -> None:
            for edge in edges:
                if str(edge.get("from") or "") != source_id:
                    continue
                target = str(edge.get("to") or "")
                if target not in active_ids:
                    kind = str(edge.get("kind") or "")
                    if kind == LOOP_EXIT_KIND and target in nodes:
                        pass
                    elif only_ids is not None and target not in only_ids:
                        continue
                    elif target not in active_ids and kind != LOOP_EXIT_KIND:
                        continue
                edge_case = str(edge.get("case") or "")
                if case is not None:
                    if edge_case and edge_case != case:
                        continue
                    if not edge_case and case != BRANCH_ELSE_CASE:
                        # unlabeled edges from a branch are ignored when a case is chosen
                        source_type = str(nodes.get(source_id, {}).get("type") or "")
                        if source_type.startswith("branch."):
                            continue
                activated.add((source_id, target, edge_case))

        if START_NODE_ID in completed:
            activate_from(START_NODE_ID)

        last_output = completed.get(START_NODE_ID, "")
        guard = 0
        while guard < 200:
            guard += 1
            ready: list[str] = []
            for node_id in active_ids:
                if node_id in completed or node_id == START_NODE_ID:
                    continue
                incoming = [
                    (source, target, case)
                    for source, target, case in activated
                    if target == node_id
                ]
                if not incoming:
                    # Entry nodes of a subgraph (loop body) with no incoming body edges.
                    has_any_edge = any(
                        str(edge.get("to") or "") == node_id
                        and str(edge.get("from") or "") in active_ids
                        for edge in edges
                    )
                    if has_any_edge:
                        continue
                    if only_ids is not None:
                        ready.append(node_id)
                    continue
                if all(source in completed for source, _target, _case in incoming):
                    ready.append(node_id)
            if not ready:
                break

            async def run_one(node_id: str) -> tuple[str, str, str | None]:
                node = nodes[node_id]
                try:
                    output, case = await asyncio.wait_for(
                        self._execute_node(
                            node,
                            task=task,
                            variables=variables,
                            emit_if_needed=emit_if_needed,
                        ),
                        timeout=self.node_timeout_seconds,
                    )
                except TimeoutError as exc:
                    logger.error(
                        "[自动化] 节点超时: id=%s node=%s timeout=%.0fs",
                        self._task_id(),
                        node_id,
                        self.node_timeout_seconds,
                    )
                    raise WorkflowError(
                        f"node timeout after {self.node_timeout_seconds}s",
                        node_id=node_id,
                    ) from exc
                return node_id, output, case

            results = await asyncio.gather(
                *[run_one(node_id) for node_id in ready],
                return_exceptions=True,
            )
            for item in results:
                if isinstance(item, BaseException):
                    if isinstance(item, WorkflowError):
                        raise item
                    raise WorkflowError(str(item)) from item
                node_id, output, case = item
                completed[node_id] = output
                last_output = output
                assign_node_output(variables, nodes.get(node_id) or {}, output)
                activate_from(node_id, case)
        return last_output

    async def _execute_node(
        self,
        node: dict[str, Any],
        *,
        task: dict[str, Any],
        variables: dict[str, Any],
        emit_if_needed: Callable[[dict[str, Any], str], Awaitable[None]],
    ) -> tuple[str, str | None]:
        node_id = str(node.get("id") or "")
        node_type = str(node.get("type") or "")
        started = time.perf_counter()
        logger.info(
            "[自动化] 节点开始: id=%s node=%s type=%s",
            self._task_id(),
            node_id,
            node_type,
        )
        output = ""
        case: str | None = None
        try:
            if node_type == "tool":
                try:
                    output = await self._run_tool(node, variables)
                except Exception as exc:
                    if self._continue_on_tool_error:
                        logger.warning(
                            "[自动化] 工具失败但继续: id=%s node=%s error=%s",
                            self._task_id(),
                            node_id,
                            exc,
                        )
                        output = f"执行失败: {exc}"
                    else:
                        raise
            elif node_type == "template":
                output = render_template(str(node.get("template") or ""), variables)
            elif node_type == "llm.blank":
                output = await self._run_blank_llm(node, variables)
            elif node_type == "llm.agent":
                output = await self._run_agent(node, variables)
            elif node_type == "llm.main":
                output = await self._run_main(node, variables)
            elif node_type == "branch.if":
                case = self._eval_branch_if(node, variables)
                logger.info(
                    "[自动化] 分支: id=%s node=%s type=%s case=%s",
                    self._task_id(),
                    node_id,
                    node_type,
                    case,
                )
                await emit_if_needed(node, "")
            elif node_type == "branch.llm":
                case = await self._eval_branch_llm(node, variables)
                logger.info(
                    "[自动化] 分支: id=%s node=%s type=%s case=%s",
                    self._task_id(),
                    node_id,
                    node_type,
                    case,
                )
            elif node_type == "loop.times":
                output = await self._run_loop_times(
                    node, task=task, variables=variables, emit_if_needed=emit_if_needed
                )
            elif node_type == "loop.each":
                output = await self._run_loop_each(
                    node, task=task, variables=variables, emit_if_needed=emit_if_needed
                )
            else:
                raise WorkflowError(f"unknown node type: {node_type}", node_id=node_id)
            if case is None:
                await emit_if_needed(node, output)
            else:
                output = case
        except WorkflowError:
            raise
        except Exception as exc:
            raise WorkflowError(str(exc), node_id=node_id) from exc

        logger.info(
            "[自动化] 节点完成: id=%s node=%s type=%s elapsed=%.2fs out_len=%s case=%s preview=%s",
            self._task_id(),
            node_id,
            node_type,
            time.perf_counter() - started,
            len(output),
            case or "-",
            preview_text(output),
        )
        return output, case

    async def _run_tool(self, node: dict[str, Any], variables: dict[str, Any]) -> str:
        tool_name = render_template(str(node.get("tool_name") or ""), variables).strip()
        if not tool_name:
            raise WorkflowError(
                "tool_name is required", node_id=str(node.get("id") or "")
            )
        args_raw = node.get("args")
        if args_raw is None:
            args_raw = node.get("tool_args") or {}
        args = render_value(args_raw, variables)
        if not isinstance(args, dict):
            args = {}
        result = await self.execute_tool(tool_name, args, self.tool_context)
        logger.debug(
            "[自动化] 工具返回: id=%s node=%s tool=%s preview=%s",
            self._task_id(),
            str(node.get("id") or ""),
            tool_name,
            preview_text(result, limit=200),
        )
        return _stringify(result)

    async def _run_agent(self, node: dict[str, Any], variables: dict[str, Any]) -> str:
        agent = render_template(str(node.get("agent") or ""), variables).strip()
        if not agent:
            raise WorkflowError("agent is required", node_id=str(node.get("id") or ""))
        prompt = render_template(
            str(node.get("input") or node.get("prompt") or ""), variables
        )
        result = await self.execute_tool(agent, {"prompt": prompt}, self.tool_context)
        return _stringify(result)

    async def _run_main(self, node: dict[str, Any], variables: dict[str, Any]) -> str:
        prompt = render_template(str(node.get("prompt") or ""), variables)
        extra = {
            "scheduled_self_call": True,
            "automation_id": str(self.tool_context.get("scheduled_task_id") or ""),
            "automation_name": str(self.tool_context.get("scheduled_task_name") or ""),
        }
        return await self.ask_main(prompt, extra)

    async def _run_blank_llm(
        self, node: dict[str, Any], variables: dict[str, Any]
    ) -> str:
        system_prompt = render_template(str(node.get("system_prompt") or ""), variables)
        user_prompt = render_template(str(node.get("user_prompt") or ""), variables)
        selected = filter_openai_tools(
            self.get_openai_tools(),
            tools=list(node.get("tools") or [])
            if isinstance(node.get("tools"), list)
            else None,
            toolsets=list(node.get("toolsets") or [])
            if isinstance(node.get("toolsets"), list)
            else None,
            agents=list(node.get("agents") or [])
            if isinstance(node.get("agents"), list)
            else None,
        )
        messages: list[dict[str, Any]] = []
        if system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        max_iterations = int(
            node.get("max_iterations") or self.blank_llm_max_iterations
        )
        max_iterations = max(1, min(max_iterations, self.blank_llm_max_iterations))
        last_content = ""
        transport_state: dict[str, Any] | None = None
        for _iteration in range(max_iterations):
            result = await self.submit_llm(
                model_config=self.agent_config,
                messages=messages,
                tools=selected or None,
                tool_choice="auto" if selected else None,
                call_type="automation:blank",
                max_tokens=getattr(self.agent_config, "max_tokens", None),
                transport_state=transport_state,
            )
            tool_name_map = (
                result.get("_tool_name_map") if isinstance(result, dict) else None
            )
            api_to_internal: dict[str, str] = {}
            if isinstance(tool_name_map, dict):
                raw = tool_name_map.get("api_to_internal")
                if isinstance(raw, dict):
                    api_to_internal = {
                        str(key): str(value) for key, value in raw.items()
                    }
            next_transport = (
                result.get("_transport_state") if isinstance(result, dict) else None
            )
            transport_state = (
                next_transport if isinstance(next_transport, dict) else None
            )
            choice = (result.get("choices") or [{}])[0]
            message = choice.get("message") if isinstance(choice, dict) else {}
            if not isinstance(message, dict):
                message = {}
            content = str(message.get("content") or "")
            tool_calls = message.get("tool_calls") or []
            if content.strip():
                last_content = content
            if not tool_calls:
                return last_content
            messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                }
            )
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                function_raw = tool_call.get("function")
                function: dict[str, Any] = (
                    function_raw if isinstance(function_raw, dict) else {}
                )
                raw_name = str(function.get("name") or "")
                internal_name = api_to_internal.get(raw_name, raw_name).replace(
                    "-_-", "."
                )
                raw_args = function.get("arguments") or "{}"
                if isinstance(raw_args, dict):
                    args = raw_args
                else:
                    try:
                        parsed = json.loads(str(raw_args))
                        args = parsed if isinstance(parsed, dict) else {}
                    except json.JSONDecodeError:
                        args = {}
                try:
                    tool_result = await self.execute_tool(
                        internal_name, args, self.tool_context
                    )
                    payload = _stringify(tool_result)
                except Exception as exc:
                    payload = f"工具执行失败: {exc}"
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(tool_call.get("id") or ""),
                        "name": raw_name,
                        "content": payload,
                    }
                )
        return last_content or "达到最大迭代次数"

    def _eval_branch_if(self, node: dict[str, Any], variables: dict[str, Any]) -> str:
        source = str(node.get("input") or "{{trigger.text_original}}")
        text = render_template(source, variables)
        sender_raw = variables.get("trigger", {})
        sender_id: int | None = None
        if isinstance(sender_raw, dict):
            sender_value = sender_raw.get("sender_id")
            if sender_value is not None:
                try:
                    sender_id = int(sender_value)
                except (TypeError, ValueError):
                    sender_id = None
        cases = node.get("cases")
        if isinstance(cases, list):
            for case in cases:
                if not isinstance(case, dict):
                    continue
                case_id = str(case.get("id") or "").strip()
                if not case_id:
                    continue
                if match_condition_on_text(text, case, sender_id=sender_id) is not None:
                    return case_id
                clock = case.get("clock") if isinstance(case.get("clock"), dict) else {}
                if (
                    clock
                    and not str(case.get("text") or "")
                    and not case.get("mentions")
                ):
                    if clock_matches(
                        datetime.now(),
                        after=str(clock.get("after") or "") or None,
                        before=str(clock.get("before") or "") or None,
                        weekdays=[
                            int(item)
                            for item in clock.get("weekdays") or []
                            if str(item).isdigit()
                        ]
                        or None,
                    ):
                        return case_id
        return BRANCH_ELSE_CASE

    async def _eval_branch_llm(
        self, node: dict[str, Any], variables: dict[str, Any]
    ) -> str:
        options_raw = node.get("options")
        if not isinstance(options_raw, list):
            return BRANCH_ELSE_CASE
        options: list[dict[str, Any]] = [
            item for item in options_raw if isinstance(item, dict)
        ]
        tools = []
        id_by_tool: dict[str, str] = {}
        for option in options:
            option_id = str(option.get("id") or "").strip()
            if not option_id:
                continue
            tool_name = option_tool_name(option_id)
            id_by_tool[tool_name] = option_id
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": str(option.get("description") or option_id),
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            )
        prompt = render_template(str(node.get("input") or ""), variables)
        messages = [{"role": "user", "content": prompt}]
        result = await self.submit_llm(
            model_config=self.agent_config,
            messages=messages,
            tools=tools,
            tool_choice="required",
            call_type="automation:branch",
            max_tokens=getattr(self.agent_config, "max_tokens", None),
        )
        choice = (result.get("choices") or [{}])[0]
        message = choice.get("message") if isinstance(choice, dict) else {}
        tool_calls = (
            message.get("tool_calls") or [] if isinstance(message, dict) else []
        )
        if tool_calls and isinstance(tool_calls[0], dict):
            function = tool_calls[0].get("function")
            raw_name = ""
            if isinstance(function, dict):
                raw_name = str(function.get("name") or "")
            mapped = id_by_tool.get(raw_name)
            if mapped:
                return mapped
            prefix = "choose_"
            if raw_name.startswith(prefix):
                return raw_name[len(prefix) :]
        return (
            str(options[0].get("id") or BRANCH_ELSE_CASE)
            if options
            else BRANCH_ELSE_CASE
        )

    async def _run_loop_times(
        self,
        node: dict[str, Any],
        *,
        task: dict[str, Any],
        variables: dict[str, Any],
        emit_if_needed: Callable[[dict[str, Any], str], Awaitable[None]],
    ) -> str:
        count = int(node.get("count") or self.loop_max_iterations)
        max_iterations = min(
            int(node.get("max_iterations") or self.loop_max_iterations),
            self.loop_max_iterations,
        )
        count = max(0, min(count, max_iterations))
        body = {
            str(item).strip() for item in (node.get("body") or []) if str(item).strip()
        }
        logger.info(
            "[自动化] 循环 times: id=%s node=%s count=%s body=%s",
            self._task_id(),
            str(node.get("id") or ""),
            count,
            ",".join(sorted(body)) or "-",
        )
        until = node.get("until") if isinstance(node.get("until"), dict) else None
        last = ""
        for index in range(count):
            if until is not None:
                source = str(until.get("input") or "{{trigger.text_original}}")
                text = render_template(source, variables)
                sender_raw = variables.get("trigger", {})
                sender_id: int | None = None
                if (
                    isinstance(sender_raw, dict)
                    and sender_raw.get("sender_id") is not None
                ):
                    try:
                        sender_id = int(sender_raw["sender_id"])
                    except (TypeError, ValueError):
                        sender_id = None
                if (
                    match_condition_on_text(text, until, sender_id=sender_id)
                    is not None
                ):
                    logger.info(
                        "[自动化] 循环 until 命中，提前结束: id=%s node=%s index=%s",
                        self._task_id(),
                        str(node.get("id") or ""),
                        index,
                    )
                    break
            logger.debug(
                "[自动化] 循环迭代: id=%s node=%s index=%s/%s",
                self._task_id(),
                str(node.get("id") or ""),
                index,
                count,
            )
            variables["index"] = index
            last = await self._run_graph(
                task,
                variables=variables,
                emit_if_needed=emit_if_needed,
                include_bodies=True,
                only_ids=body,
            )
        return last

    async def _run_loop_each(
        self,
        node: dict[str, Any],
        *,
        task: dict[str, Any],
        variables: dict[str, Any],
        emit_if_needed: Callable[[dict[str, Any], str], Awaitable[None]],
    ) -> str:
        source = render_template(str(node.get("source") or ""), variables)
        items = _parse_each_source(source)
        max_iterations = min(
            int(node.get("max_iterations") or self.loop_max_iterations),
            self.loop_max_iterations,
        )
        items = items[:max_iterations]
        body = {
            str(item).strip() for item in (node.get("body") or []) if str(item).strip()
        }
        logger.info(
            "[自动化] 循环 each: id=%s node=%s items=%s body=%s",
            self._task_id(),
            str(node.get("id") or ""),
            len(items),
            ",".join(sorted(body)) or "-",
        )
        last = ""
        for index, item in enumerate(items):
            variables["index"] = index
            variables["item"] = item
            last = await self._run_graph(
                task,
                variables=variables,
                emit_if_needed=emit_if_needed,
                include_bodies=True,
                only_ids=body,
            )
        return last
