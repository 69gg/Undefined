"""请求级工具搜索与按需 schema 投影。"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Self

TOOL_SEARCH_NAME = "tool_search"

_CAMEL_BOUNDARY_1_RE = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_BOUNDARY_2_RE = re.compile(r"([a-z0-9])([A-Z])")
_NAME_SEPARATOR_RE = re.compile(r"[._-]+")
_SELECT_QUERY_RE = re.compile(r"^select\s*:(.*)$", re.IGNORECASE | re.DOTALL)
_SCHEMA_CONTAINER_KEYS: tuple[str, ...] = (
    "$defs",
    "definitions",
    "properties",
    "patternProperties",
)
_SCHEMA_VALUE_KEYS: tuple[str, ...] = (
    "additionalProperties",
    "contains",
    "else",
    "if",
    "items",
    "not",
    "propertyNames",
    "then",
)
_SCHEMA_LIST_KEYS: tuple[str, ...] = ("allOf", "anyOf", "oneOf", "prefixItems")


class ToolSearchNameCollisionError(ValueError):
    """完整工具目录已经占用了虚拟 ``tool_search`` 名称。"""


@dataclass(frozen=True, slots=True)
class ToolSearchResult:
    """一次工具搜索及加载操作的稳定结果。"""

    loaded: tuple[str, ...]
    already_loaded: tuple[str, ...]
    not_found: tuple[str, ...]
    truncated: bool
    total_deferred_tools: int

    def as_dict(self) -> dict[str, object]:
        """转换为可 JSON 序列化的公开结果。"""
        return {
            "loaded": list(self.loaded),
            "already_loaded": list(self.already_loaded),
            "not_found": list(self.not_found),
            "truncated": self.truncated,
            "total_deferred_tools": self.total_deferred_tools,
        }

    def to_json(self) -> str:
        """返回适合作为 tool result 的紧凑 JSON。"""
        return json.dumps(self.as_dict(), ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class _SearchDocument:
    name: str
    name_parts: tuple[str, ...]
    normalized_name: str
    parameter_names: tuple[str, ...]
    description_text: str

    def contains(self, term: str) -> bool:
        return (
            term in self.normalized_name
            or any(term in parameter_name for parameter_name in self.parameter_names)
            or term in self.description_text
        )

    def score(self, term: str) -> int:
        score = 0
        if term in self.name_parts:
            score += 10
        elif any(term in part for part in self.name_parts):
            score += 5
        elif term in self.normalized_name:
            score += 3

        if any(term in parameter_name for parameter_name in self.parameter_names):
            score += 3
        if term in self.description_text:
            score += 2
        return score


def _tool_name(schema: Mapping[str, Any]) -> str | None:
    function = schema.get("function")
    if not isinstance(function, Mapping):
        return None
    raw_name = function.get("name")
    if not isinstance(raw_name, str):
        return None
    name = raw_name.strip()
    return name or None


def _split_identifier(value: str) -> tuple[str, ...]:
    value = _CAMEL_BOUNDARY_1_RE.sub(r"\1 \2", value)
    value = _CAMEL_BOUNDARY_2_RE.sub(r"\1 \2", value)
    value = _NAME_SEPARATOR_RE.sub(" ", value)
    return tuple(part.casefold() for part in value.split() if part)


def _collect_parameter_index(parameters: object) -> tuple[tuple[str, ...], str]:
    parameter_names: list[str] = []
    descriptions: list[str] = []
    visited: set[int] = set()

    def visit(node: object) -> None:
        if not isinstance(node, Mapping):
            return
        node_id = id(node)
        if node_id in visited:
            return
        visited.add(node_id)

        description = node.get("description")
        if isinstance(description, str) and description.strip():
            descriptions.append(description.casefold())

        properties = node.get("properties")
        if isinstance(properties, Mapping):
            for raw_name in properties:
                if isinstance(raw_name, str) and raw_name.strip():
                    parameter_names.append(" ".join(_split_identifier(raw_name)))

        for key in _SCHEMA_CONTAINER_KEYS:
            container = node.get(key)
            if isinstance(container, Mapping):
                for child in container.values():
                    visit(child)
        for key in _SCHEMA_VALUE_KEYS:
            visit(node.get(key))
        for key in _SCHEMA_LIST_KEYS:
            children = node.get(key)
            if isinstance(children, Sequence) and not isinstance(
                children, (str, bytes, bytearray)
            ):
                for child in children:
                    visit(child)

    visit(parameters)
    return tuple(parameter_names), " ".join(descriptions)


def _build_search_document(name: str, schema: Mapping[str, Any]) -> _SearchDocument:
    function = schema.get("function")
    function_mapping = function if isinstance(function, Mapping) else {}
    description = function_mapping.get("description")
    function_description = (
        description.casefold() if isinstance(description, str) else ""
    )
    parameter_names, parameter_descriptions = _collect_parameter_index(
        function_mapping.get("parameters")
    )
    name_parts = _split_identifier(name)
    return _SearchDocument(
        name=name,
        name_parts=name_parts,
        normalized_name=" ".join(name_parts),
        parameter_names=parameter_names,
        description_text=" ".join(
            part for part in (function_description, parameter_descriptions) if part
        ),
    )


def _build_tool_search_schema(max_results: int) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_SEARCH_NAME,
            "description": (
                "Search and load deferred tool schemas for this request. "
                "Loaded tools become callable starting with the next model turn."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Use select:name_a,name_b for exact selection, a full "
                            "tool name, keywords, or +term to require a keyword."
                        ),
                    },
                    "max_results": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": max_results,
                        "description": "Maximum matches to load, capped by configuration.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    }


class ToolSearchSession:
    """保存一次主 AI 请求内的工具目录、加载集合和执行快照。

    ``request_tools`` 会冻结当前模型轮次实际看到的工具名；之后执行
    ``execute`` 加载的新工具只会出现在下一次 ``request_tools`` 调用中。
    """

    def __init__(
        self,
        schemas: Sequence[Mapping[str, Any]],
        always_loaded_names: Collection[str],
        max_results: int,
        *,
        hidden_tool_names: Collection[str] = (),
    ) -> None:
        if isinstance(max_results, bool) or max_results < 1:
            raise ValueError("max_results must be a positive integer")

        hidden_names = {name for name in hidden_tool_names if name}
        catalog: dict[str, dict[str, Any]] = {}
        for schema in schemas:
            name = _tool_name(schema)
            if name == TOOL_SEARCH_NAME:
                raise ToolSearchNameCollisionError(
                    f"tool catalog already contains {TOOL_SEARCH_NAME!r}"
                )
            if name is None or name in hidden_names or name in catalog:
                continue
            catalog[name] = copy.deepcopy(dict(schema))

        self._max_results = max_results
        self._catalog = catalog
        self._catalog_casefold = self._build_casefold_lookup(catalog)
        self._documents = {
            name: _build_search_document(name, schema)
            for name, schema in catalog.items()
        }
        self._tool_search_schema = _build_tool_search_schema(max_results)

        loaded_names: set[str] = set()
        for requested_name in always_loaded_names:
            canonical_name = self._resolve_catalog_name(requested_name)
            if canonical_name is not None:
                loaded_names.add(canonical_name)
        self._loaded_names = loaded_names
        self._deferred_tool_names = tuple(
            sorted(
                (name for name in catalog if name not in loaded_names),
                key=lambda name: (name.casefold(), name),
            )
        )
        self._last_exposed_names = frozenset((*self._loaded_names, TOOL_SEARCH_NAME))

    @classmethod
    def create(
        cls,
        schemas: Sequence[Mapping[str, Any]],
        always_loaded_names: Collection[str],
        max_results: int,
        *,
        hidden_tool_names: Collection[str] = (),
    ) -> Self | None:
        """创建 session；虚拟工具重名时返回 ``None`` 供调用方回退全量。"""
        try:
            return cls(
                schemas,
                always_loaded_names,
                max_results,
                hidden_tool_names=hidden_tool_names,
            )
        except ToolSearchNameCollisionError:
            return None

    @staticmethod
    def _build_casefold_lookup(catalog: Mapping[str, object]) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for name in sorted(catalog, key=lambda value: (value.casefold(), value)):
            lookup.setdefault(name.casefold(), name)
        return lookup

    @property
    def catalog_tool_names(self) -> tuple[str, ...]:
        """返回当前权限和隐藏规则过滤后的规范工具名。"""
        return tuple(self._catalog)

    @property
    def deferred_tool_names(self) -> tuple[str, ...]:
        """返回初始被延迟的工具名目录，按名称稳定排序。"""
        return self._deferred_tool_names

    @property
    def loaded_tool_names(self) -> frozenset[str]:
        """返回将在下一次模型请求中携带 schema 的目录工具名。"""
        return frozenset(self._loaded_names)

    @property
    def tool_search_schema(self) -> dict[str, Any]:
        """返回虚拟 ``tool_search`` schema 的隔离副本。"""
        return copy.deepcopy(self._tool_search_schema)

    def request_tools(self) -> list[dict[str, Any]]:
        """生成本轮模型请求的 schema，并冻结本轮执行白名单。"""
        tools = [
            copy.deepcopy(schema)
            for name, schema in self._catalog.items()
            if name in self._loaded_names
        ]
        tools.append(copy.deepcopy(self._tool_search_schema))
        self._last_exposed_names = frozenset((*self._loaded_names, TOOL_SEARCH_NAME))
        return tools

    def exposed_tool_names(self) -> frozenset[str]:
        """返回最近一次 ``request_tools`` 暴露并允许本轮执行的工具名。"""
        return self._last_exposed_names

    def execute(self, arguments: Mapping[str, Any]) -> str:
        """执行虚拟工具调用并返回稳定 JSON；额外字段不会进入搜索目录。"""
        raw_query = arguments.get("query")
        query = raw_query if isinstance(raw_query, str) else ""
        raw_max_results = arguments.get("max_results")
        requested_max = (
            raw_max_results
            if isinstance(raw_max_results, int)
            and not isinstance(raw_max_results, bool)
            else None
        )
        return self.search_and_load(query, requested_max).to_json()

    def search_and_load(
        self, query: str, max_results: int | None = None
    ) -> ToolSearchResult:
        """按精确选择或关键词搜索，并单调扩展下一轮加载集合。"""
        normalized_query = query.strip()
        limit = self._effective_limit(max_results)
        select_match = _SELECT_QUERY_RE.fullmatch(normalized_query)
        if select_match is not None:
            return self._select_and_load(select_match.group(1), normalized_query, limit)

        exact_name = self._resolve_exact_name(normalized_query)
        if exact_name is not None:
            return self._load_matches((exact_name,), (), truncated=False)

        required_terms, optional_terms = self._query_terms(normalized_query)
        scoring_terms = (*required_terms, *optional_terms)
        if not scoring_terms:
            missing = (normalized_query,) if normalized_query else ()
            return self._load_matches((), missing, truncated=False)

        scored: list[tuple[int, str]] = []
        for name in self._deferred_tool_names:
            document = self._documents[name]
            if not all(document.contains(term) for term in required_terms):
                continue
            score = sum(document.score(term) for term in scoring_terms)
            if score > 0:
                scored.append((score, name))
        scored.sort(key=lambda item: (-item[0], item[1].casefold(), item[1]))
        matched_names = tuple(name for _, name in scored)
        truncated = len(matched_names) > limit
        selected_names = matched_names[:limit]
        missing = (normalized_query,) if not selected_names else ()
        return self._load_matches(selected_names, missing, truncated=truncated)

    def _resolve_catalog_name(self, requested_name: object) -> str | None:
        if not isinstance(requested_name, str):
            return None
        stripped_name = requested_name.strip()
        if stripped_name in self._catalog:
            return stripped_name
        return self._catalog_casefold.get(stripped_name.casefold())

    def _resolve_exact_name(self, requested_name: str) -> str | None:
        if requested_name.casefold() == TOOL_SEARCH_NAME.casefold():
            return TOOL_SEARCH_NAME
        return self._resolve_catalog_name(requested_name)

    def _effective_limit(self, requested_max: int | None) -> int:
        if (
            requested_max is None
            or isinstance(requested_max, bool)
            or requested_max >= self._max_results
        ):
            return self._max_results
        return max(1, requested_max)

    @staticmethod
    def _query_terms(query: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        required_terms: list[str] = []
        optional_terms: list[str] = []
        for raw_term in query.casefold().split():
            if raw_term.startswith("+") and len(raw_term) > 1:
                required_terms.append(raw_term[1:])
            elif raw_term:
                optional_terms.append(raw_term)
        return tuple(required_terms), tuple(optional_terms)

    def _select_and_load(
        self, selection: str, original_query: str, limit: int
    ) -> ToolSearchResult:
        matched_names: list[str] = []
        missing_names: list[str] = []
        seen_matches: set[str] = set()
        seen_missing: set[str] = set()
        for raw_name in selection.split(","):
            requested_name = raw_name.strip()
            if not requested_name:
                continue
            canonical_name = self._resolve_exact_name(requested_name)
            if canonical_name is None:
                missing_key = requested_name.casefold()
                if missing_key not in seen_missing:
                    missing_names.append(requested_name)
                    seen_missing.add(missing_key)
                continue
            if canonical_name not in seen_matches:
                matched_names.append(canonical_name)
                seen_matches.add(canonical_name)

        if not matched_names and not missing_names and original_query:
            missing_names.append(original_query)
        truncated = len(matched_names) > limit
        return self._load_matches(
            tuple(matched_names[:limit]), tuple(missing_names), truncated=truncated
        )

    def _load_matches(
        self,
        matched_names: Sequence[str],
        missing_names: Sequence[str],
        *,
        truncated: bool,
    ) -> ToolSearchResult:
        loaded: list[str] = []
        already_loaded: list[str] = []
        for name in matched_names:
            if name == TOOL_SEARCH_NAME or name in self._loaded_names:
                already_loaded.append(name)
                continue
            self._loaded_names.add(name)
            loaded.append(name)
        return ToolSearchResult(
            loaded=tuple(loaded),
            already_loaded=tuple(already_loaded),
            not_found=tuple(missing_names),
            truncated=truncated,
            total_deferred_tools=len(self._deferred_tool_names),
        )


__all__ = [
    "TOOL_SEARCH_NAME",
    "ToolSearchNameCollisionError",
    "ToolSearchResult",
    "ToolSearchSession",
]
