from __future__ import annotations

import json
from datetime import datetime, timezone
import os
import time
from types import SimpleNamespace
from typing import Any, cast

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer
from Undefined.memory import Memory
from Undefined.api.routes.memory import memory_list_handler


class _DummyMemoryStorage:
    def __init__(self) -> None:
        self._items = [
            Memory(uuid="m1", fact="用户喜欢猫", created_at="2026-02-25 10:00:00"),
            Memory(uuid="m2", fact="用户偏好 Python", created_at="2026-02-25 11:00:00"),
        ]

    def get_all(self) -> list[Memory]:
        return list(self._items)

    def count(self) -> int:
        return len(self._items)

    async def add(self, _fact: str) -> str:
        raise AssertionError("memory query endpoint should be read-only")

    async def update(self, _uuid: str, _fact: str) -> bool:
        raise AssertionError("memory query endpoint should be read-only")

    async def delete(self, _uuid: str) -> bool:
        raise AssertionError("memory query endpoint should be read-only")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query_kind", "expected"),
    [
        ("naive", ["m1"]),
        ("z", ["m1"]),
        ("offset", ["m1"]),
        ("mixed", ["m1"]),
        ("reversed_mixed", ["m1", "m2"]),
        ("from", ["m2"]),
        ("to", ["m1"]),
    ],
)
async def test_memory_http_filters_compare_instants_and_include_boundaries(
    query_kind: str, expected: list[str]
) -> None:
    storage = _DummyMemoryStorage()
    first_local = datetime.fromisoformat(storage._items[0].created_at)
    second_local = datetime.fromisoformat(storage._items[1].created_at)
    first_utc = first_local.astimezone(timezone.utc)
    second_utc = second_local.astimezone(timezone.utc)
    first_z = first_utc.isoformat().replace("+00:00", "Z")
    second_z = second_utc.isoformat().replace("+00:00", "Z")
    first_offset = first_local.astimezone().isoformat()
    queries = {
        "naive": {
            "time_from": first_local.isoformat(),
            "time_to": first_local.isoformat(),
        },
        "z": {"time_from": first_z, "time_to": first_z},
        "offset": {"time_from": first_offset, "time_to": first_offset},
        "mixed": {"time_from": first_z, "time_to": first_local.isoformat()},
        "reversed_mixed": {"time_from": second_local.isoformat(), "time_to": first_z},
        "from": {"time_from": second_z},
        "to": {"time_to": first_z},
    }
    # 混合新旧存储格式，输出仍保留原始时间字符串。
    storage._items.extend(
        [
            Memory(uuid="old", fact="旧记录", created_at="2020-01-01T00:00:00Z"),
            Memory(uuid="invalid", fact="无效时间", created_at="invalid"),
        ]
    )
    context: Any = SimpleNamespace(ai=SimpleNamespace(memory_storage=storage))

    async def handle(request: web.Request) -> web.Response:
        return await memory_list_handler(context, request)

    app = web.Application()
    app.router.add_get("/api/v1/memory", handle)
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/api/v1/memory", params=queries[query_kind])
        assert response.status == 200
        body = await response.json()
    if query_kind == "to":
        expected = ["old", *expected]
    assert [item["uuid"] for item in body["items"]] == expected
    assert all(
        item["created_at"] in {row.created_at for row in storage._items}
        for item in body["items"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["time_from", "time_to"])
@pytest.mark.parametrize(
    "value", ["invalid", "2026-02-30T00:00:00", "2026-01-01T00:00:00+25:00"]
)
async def test_memory_invalid_time_filter_returns_400(field: str, value: str) -> None:
    context: Any = SimpleNamespace(
        ai=SimpleNamespace(memory_storage=_DummyMemoryStorage())
    )
    request = cast(web.Request, SimpleNamespace(query={field: value}))
    response = await memory_list_handler(context, request)
    assert response.status == 400
    assert json.loads(response.text or "{}") == {
        "error": f"{field} must be ISO datetime"
    }


@pytest.mark.asyncio
@pytest.mark.skipif(not hasattr(time, "tzset"), reason="需要 POSIX 时区切换 API")
@pytest.mark.parametrize("system_zone", ["UTC", "Asia/Shanghai", "America/New_York"])
@pytest.mark.parametrize("local_time", ["2026-02-25T10:00:00", "2026-07-25T10:00:00"])
async def test_memory_naive_time_uses_system_zone_at_record_date(
    monkeypatch: pytest.MonkeyPatch, system_zone: str, local_time: str
) -> None:
    from zoneinfo import ZoneInfo

    utc_time = (
        datetime.fromisoformat(local_time)
        .replace(tzinfo=ZoneInfo(system_zone))
        .astimezone(timezone.utc)
    )
    storage = _DummyMemoryStorage()
    storage._items = [Memory(uuid="m1", fact="当地时间", created_at=local_time)]
    context: Any = SimpleNamespace(ai=SimpleNamespace(memory_storage=storage))
    request = cast(
        web.Request,
        SimpleNamespace(
            query={"time_from": utc_time.isoformat(), "time_to": utc_time.isoformat()}
        ),
    )
    previous_zone = os.environ.get("TZ")
    try:
        monkeypatch.setenv("TZ", system_zone)
        time.tzset()
        response = await memory_list_handler(context, request)
        assert response.status == 200
        assert json.loads(response.text or "{}")["total"] == 1
    finally:
        if previous_zone is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", previous_zone)
        time.tzset()


@pytest.mark.asyncio
async def test_runtime_memory_endpoint_read_only_and_searchable() -> None:
    context = RuntimeAPIContext(
        config_getter=lambda: SimpleNamespace(
            api=SimpleNamespace(
                enabled=True,
                host="127.0.0.1",
                port=8788,
                auth_key="changeme",
                openapi_enabled=True,
            )
        ),
        onebot=SimpleNamespace(connection_status=lambda: {}),
        ai=SimpleNamespace(memory_storage=_DummyMemoryStorage()),
        command_dispatcher=SimpleNamespace(),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=SimpleNamespace(),
    )
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)

    request_all = cast(web.Request, cast(Any, SimpleNamespace(query={})))
    response_all = await server._memory_handler(request_all)
    response_all_text = response_all.text
    assert response_all_text is not None
    payload_all = json.loads(response_all_text)
    assert payload_all["total"] == 2
    assert payload_all["items"][0]["uuid"] == "m1"

    request_query = cast(web.Request, cast(Any, SimpleNamespace(query={"q": "python"})))
    response_query = await server._memory_handler(request_query)
    response_query_text = response_query.text
    assert response_query_text is not None
    payload_query = json.loads(response_query_text)
    assert payload_query["total"] == 1
    assert payload_query["items"][0]["uuid"] == "m2"
