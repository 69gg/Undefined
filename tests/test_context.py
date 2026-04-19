"""Tests for Undefined.context module."""

from __future__ import annotations

import logging

import pytest

from Undefined.context import (
    RequestContext,
    RequestContextFilter,
    get_group_id,
    get_request_id,
    get_request_type,
    get_sender_id,
    get_user_id,
)


class TestRequestContextManager:
    """Tests for RequestContext async context manager."""

    async def test_enter_sets_current(self) -> None:
        async with RequestContext(request_type="group", group_id=123) as ctx:
            assert RequestContext.current() is ctx

    async def test_exit_clears_current(self) -> None:
        async with RequestContext(request_type="group"):
            pass
        assert RequestContext.current() is None

    async def test_request_id_generated(self) -> None:
        async with RequestContext(request_type="private") as ctx:
            assert ctx.request_id is not None
            assert len(ctx.request_id) > 0

    async def test_request_id_is_uuid(self) -> None:
        import uuid

        async with RequestContext(request_type="private") as ctx:
            uuid.UUID(ctx.request_id)

    async def test_nested_contexts(self) -> None:
        async with RequestContext(request_type="group", group_id=1) as outer:
            assert RequestContext.current() is outer
            async with RequestContext(request_type="private", user_id=99) as inner:
                assert RequestContext.current() is inner
                assert inner.user_id == 99
            assert RequestContext.current() is outer
            assert outer.group_id == 1

    async def test_metadata(self) -> None:
        async with RequestContext(request_type="api", extra_key="value") as ctx:
            assert ctx.metadata["extra_key"] == "value"


class TestRequestContextResources:
    """Tests for resource management."""

    async def test_set_and_get_resource(self) -> None:
        async with RequestContext(request_type="group") as ctx:
            ctx.set_resource("sender", {"name": "test"})
            assert ctx.get_resource("sender") == {"name": "test"}

    async def test_get_missing_resource_default(self) -> None:
        async with RequestContext(request_type="group") as ctx:
            assert ctx.get_resource("missing") is None
            assert ctx.get_resource("missing", "fallback") == "fallback"

    async def test_resources_cleared_on_exit(self) -> None:
        ctx = RequestContext(request_type="group")
        async with ctx:
            ctx.set_resource("key", "value")
        assert ctx.get_resource("key") is None

    async def test_get_resources_returns_copy(self) -> None:
        async with RequestContext(request_type="group") as ctx:
            ctx.set_resource("a", 1)
            ctx.set_resource("b", 2)
            resources = ctx.get_resources()
            assert resources == {"a": 1, "b": 2}
            resources["c"] = 3
            assert ctx.get_resource("c") is None


class TestRequireContext:
    """Tests for RequestContext.require()."""

    async def test_require_inside_context(self) -> None:
        async with RequestContext(request_type="group") as ctx:
            assert RequestContext.require() is ctx

    async def test_require_outside_context_raises(self) -> None:
        with pytest.raises(RuntimeError):
            RequestContext.require()


class TestHelperFunctions:
    """Tests for module-level helper functions."""

    async def test_get_group_id_inside_context(self) -> None:
        async with RequestContext(request_type="group", group_id=42):
            assert get_group_id() == 42

    async def test_get_group_id_outside_context(self) -> None:
        assert get_group_id() is None

    async def test_get_user_id_inside_context(self) -> None:
        async with RequestContext(request_type="private", user_id=7):
            assert get_user_id() == 7

    async def test_get_user_id_outside_context(self) -> None:
        assert get_user_id() is None

    async def test_get_request_id_inside_context(self) -> None:
        async with RequestContext(request_type="group"):
            rid = get_request_id()
            assert rid is not None
            assert len(rid) > 0

    async def test_get_request_id_outside_context(self) -> None:
        assert get_request_id() is None

    async def test_get_sender_id_inside_context(self) -> None:
        async with RequestContext(request_type="group", sender_id=100):
            assert get_sender_id() == 100

    async def test_get_sender_id_outside_context(self) -> None:
        assert get_sender_id() is None

    async def test_get_request_type_inside_context(self) -> None:
        async with RequestContext(request_type="private"):
            assert get_request_type() == "private"

    async def test_get_request_type_outside_context(self) -> None:
        assert get_request_type() is None


class TestRequestContextFilter:
    """Tests for RequestContextFilter logging filter."""

    async def test_filter_with_context(self) -> None:
        filt = RequestContextFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )
        async with RequestContext(
            request_type="group", group_id=10, user_id=20, sender_id=30
        ) as ctx:
            result = filt.filter(record)
            assert result is True
            assert getattr(record, "request_id") == ctx.request_id[:8]
            assert getattr(record, "group_id") == 10
            assert getattr(record, "user_id") == 20
            assert getattr(record, "sender_id") == 30

    def test_filter_without_context(self) -> None:
        filt = RequestContextFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        result = filt.filter(record)
        assert result is True
        assert getattr(record, "request_id") == "-"
        assert getattr(record, "group_id") == "-"
        assert getattr(record, "user_id") == "-"
        assert getattr(record, "sender_id") == "-"

    async def test_filter_partial_context(self) -> None:
        filt = RequestContextFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        async with RequestContext(request_type="private", user_id=5):
            filt.filter(record)
            assert getattr(record, "group_id") == "-"
            assert getattr(record, "user_id") == 5
