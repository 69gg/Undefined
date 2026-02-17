"""InflightTaskStore 单元测试"""

import asyncio

import pytest

from Undefined.inflight_task_store import (
    InflightTaskStore,
    InflightTaskLocation,
)


@pytest.fixture
def store() -> InflightTaskStore:
    """创建测试用的 InflightTaskStore 实例"""
    return InflightTaskStore(ttl_seconds=60, gc_interval=5, gc_threshold=10)


@pytest.fixture
def location_group() -> InflightTaskLocation:
    """创建测试用的群聊位置"""
    return {"type": "group", "name": "测试群", "id": 12345}


@pytest.fixture
def location_private() -> InflightTaskLocation:
    """创建测试用的私聊位置"""
    return {"type": "private", "name": "测试用户", "id": 67890}


class TestBasicOperations:
    """测试基本操作"""

    @pytest.mark.asyncio
    async def test_upsert_pending(
        self, store: InflightTaskStore, location_group: InflightTaskLocation
    ) -> None:
        """测试创建占位记录"""
        record = await store.upsert_pending(
            request_id="req-001",
            request_type="group",
            chat_id=12345,
            location_name="测试群",
            source_message="测试消息",
        )

        assert record["request_id"] == "req-001"
        assert record["status"] == "pending"
        assert record["location"]["type"] == "group"
        assert record["location"]["id"] == 12345
        assert record["source_message"] == "测试消息"
        assert "正在处理消息" in record["display_text"]

    @pytest.mark.asyncio
    async def test_upsert_pending_truncate_long_message(
        self, store: InflightTaskStore
    ) -> None:
        """测试长消息截断"""
        long_message = "x" * 200
        record = await store.upsert_pending(
            request_id="req-002",
            request_type="group",
            chat_id=12345,
            location_name="测试群",
            source_message=long_message,
        )

        assert len(record["source_message"]) <= 120
        assert record["source_message"].endswith("...")

    @pytest.mark.asyncio
    async def test_mark_ready(self, store: InflightTaskStore) -> None:
        """测试标记为就绪状态"""
        await store.upsert_pending(
            request_id="req-003",
            request_type="group",
            chat_id=12345,
            location_name="测试群",
            source_message="测试消息",
        )

        success = await store.mark_ready("req-003", "正在生成代码")
        assert success is True

        records = await store.list_for_chat(request_type="group", chat_id=12345)
        assert len(records) == 1
        assert records[0]["status"] == "ready"
        assert "正在生成代码" in records[0]["display_text"]

    @pytest.mark.asyncio
    async def test_mark_ready_nonexistent(self, store: InflightTaskStore) -> None:
        """测试标记不存在的记录"""
        success = await store.mark_ready("nonexistent", "测试")
        assert success is False

    @pytest.mark.asyncio
    async def test_clear_by_request(self, store: InflightTaskStore) -> None:
        """测试按 request_id 清除"""
        await store.upsert_pending(
            request_id="req-004",
            request_type="group",
            chat_id=12345,
            location_name="测试群",
            source_message="测试消息",
        )

        success = await store.clear_by_request("req-004")
        assert success is True

        records = await store.list_for_chat(request_type="group", chat_id=12345)
        assert len(records) == 0

    @pytest.mark.asyncio
    async def test_clear_for_chat(self, store: InflightTaskStore) -> None:
        """测试按会话清除"""
        await store.upsert_pending(
            request_id="req-005",
            request_type="group",
            chat_id=12345,
            location_name="测试群",
            source_message="测试消息",
        )

        success = await store.clear_for_chat(request_type="group", chat_id=12345)
        assert success is True

        records = await store.list_for_chat(request_type="group", chat_id=12345)
        assert len(records) == 0

    @pytest.mark.asyncio
    async def test_clear_for_chat_with_owner_check(
        self, store: InflightTaskStore
    ) -> None:
        """测试按会话清除时的 owner 校验"""
        await store.upsert_pending(
            request_id="req-006",
            request_type="group",
            chat_id=12345,
            location_name="测试群",
            source_message="测试消息",
        )

        # 错误的 owner，应该失败
        success = await store.clear_for_chat(
            request_type="group", chat_id=12345, owner_request_id="wrong-id"
        )
        assert success is False

        # 正确的 owner，应该成功
        success = await store.clear_for_chat(
            request_type="group", chat_id=12345, owner_request_id="req-006"
        )
        assert success is True

    @pytest.mark.asyncio
    async def test_list_for_chat(self, store: InflightTaskStore) -> None:
        """测试查询会话记录"""
        await store.upsert_pending(
            request_id="req-007",
            request_type="group",
            chat_id=12345,
            location_name="测试群",
            source_message="测试消息",
        )

        records = await store.list_for_chat(request_type="group", chat_id=12345)
        assert len(records) == 1
        assert records[0]["request_id"] == "req-007"

    @pytest.mark.asyncio
    async def test_list_for_chat_with_exclude(self, store: InflightTaskStore) -> None:
        """测试查询时排除指定 request_id"""
        await store.upsert_pending(
            request_id="req-008",
            request_type="group",
            chat_id=12345,
            location_name="测试群",
            source_message="测试消息",
        )

        records = await store.list_for_chat(
            request_type="group", chat_id=12345, exclude_request_id="req-008"
        )
        assert len(records) == 0

    @pytest.mark.asyncio
    async def test_upsert_overwrites_previous(self, store: InflightTaskStore) -> None:
        """测试同一会话的新占位会覆盖旧占位"""
        await store.upsert_pending(
            request_id="req-009",
            request_type="group",
            chat_id=12345,
            location_name="测试群",
            source_message="第一条消息",
        )

        await store.upsert_pending(
            request_id="req-010",
            request_type="group",
            chat_id=12345,
            location_name="测试群",
            source_message="第二条消息",
        )

        records = await store.list_for_chat(request_type="group", chat_id=12345)
        assert len(records) == 1
        assert records[0]["request_id"] == "req-010"
        assert records[0]["source_message"] == "第二条消息"


class TestConcurrency:
    """测试并发场景"""

    @pytest.mark.asyncio
    async def test_concurrent_upsert(self, store: InflightTaskStore) -> None:
        """测试并发创建占位"""

        async def create_task(i: int) -> None:
            await store.upsert_pending(
                request_id=f"req-{i}",
                request_type="group",
                chat_id=i,
                location_name=f"群{i}",
                source_message=f"消息{i}",
            )

        # 并发创建 10 个占位
        await asyncio.gather(*[create_task(i) for i in range(10)])

        # 验证每个会话都有记录
        for i in range(10):
            records = await store.list_for_chat(request_type="group", chat_id=i)
            assert len(records) == 1
            assert records[0]["request_id"] == f"req-{i}"

    @pytest.mark.asyncio
    async def test_concurrent_mark_ready(self, store: InflightTaskStore) -> None:
        """测试并发标记就绪"""
        # 先创建占位
        for i in range(5):
            await store.upsert_pending(
                request_id=f"req-{i}",
                request_type="group",
                chat_id=i,
                location_name=f"群{i}",
                source_message=f"消息{i}",
            )

        # 并发标记就绪
        results = await asyncio.gather(
            *[store.mark_ready(f"req-{i}", f"动作{i}") for i in range(5)]
        )

        assert all(results)

        # 验证所有记录都是 ready 状态
        for i in range(5):
            records = await store.list_for_chat(request_type="group", chat_id=i)
            assert len(records) == 1
            assert records[0]["status"] == "ready"

    @pytest.mark.asyncio
    async def test_concurrent_clear(self, store: InflightTaskStore) -> None:
        """测试并发清除"""
        # 先创建占位
        for i in range(5):
            await store.upsert_pending(
                request_id=f"req-{i}",
                request_type="group",
                chat_id=i,
                location_name=f"群{i}",
                source_message=f"消息{i}",
            )

        # 并发清除
        results = await asyncio.gather(
            *[store.clear_by_request(f"req-{i}") for i in range(5)]
        )

        assert all(results)

        # 验证所有记录都被清除
        for i in range(5):
            records = await store.list_for_chat(request_type="group", chat_id=i)
            assert len(records) == 0


class TestTTLAndGC:
    """测试 TTL 过期和 GC 机制"""

    @pytest.mark.asyncio
    async def test_ttl_expiration(self) -> None:
        """测试 TTL 过期"""
        store = InflightTaskStore(ttl_seconds=1, gc_interval=1, gc_threshold=100)

        await store.upsert_pending(
            request_id="req-ttl-001",
            request_type="group",
            chat_id=12345,
            location_name="测试群",
            source_message="测试消息",
        )

        # 立即查询，应该存在
        records = await store.list_for_chat(request_type="group", chat_id=12345)
        assert len(records) == 1

        # 等待超过 TTL
        await asyncio.sleep(1.5)

        # 触发 GC（通过在不同会话创建记录）
        await store.upsert_pending(
            request_id="req-ttl-002",
            request_type="group",
            chat_id=99999,
            location_name="触发GC",
            source_message="触发",
        )

        # 验证 GC 已执行且清理了过期记录
        metrics = store.get_metrics()
        assert metrics["total_gc_runs"] > 0
        assert metrics["total_expired_cleaned"] > 0

        # 原记录应该被清除（通过查询不存在的会话来避免刷新过期时间）
        # 注意：list_for_chat 会刷新找到的记录的过期时间，所以我们不能直接查询原记录
        # 我们通过检查 metrics 来验证 GC 已经清理了过期记录
        assert metrics["current_entries"] == 1  # 只剩下新创建的记录

    @pytest.mark.asyncio
    async def test_gc_by_threshold(self) -> None:
        """测试按阈值触发 GC"""
        store = InflightTaskStore(ttl_seconds=1, gc_interval=999, gc_threshold=5)

        # 创建 5 个记录
        for i in range(5):
            await store.upsert_pending(
                request_id=f"req-{i}",
                request_type="group",
                chat_id=i,
                location_name=f"群{i}",
                source_message=f"消息{i}",
            )

        metrics = store.get_metrics()
        initial_gc_runs = metrics["total_gc_runs"]

        # 等待过期
        await asyncio.sleep(1.5)

        # 创建第 6 个记录，应触发 GC（因为在添加前有5个记录，达到阈值）
        await store.upsert_pending(
            request_id="req-5",
            request_type="group",
            chat_id=5,
            location_name="群5",
            source_message="消息5",
        )

        metrics = store.get_metrics()
        assert metrics["total_gc_runs"] > initial_gc_runs
        assert metrics["total_expired_cleaned"] >= 5

    @pytest.mark.asyncio
    async def test_gc_by_interval(self) -> None:
        """测试按时间间隔触发 GC"""
        store = InflightTaskStore(ttl_seconds=1, gc_interval=2, gc_threshold=100)

        # 创建记录
        await store.upsert_pending(
            request_id="req-001",
            request_type="group",
            chat_id=12345,
            location_name="测试群",
            source_message="测试消息",
        )

        metrics = store.get_metrics()
        initial_gc_runs = metrics["total_gc_runs"]

        # 等待超过 GC 间隔和 TTL
        await asyncio.sleep(2.5)

        # 触发任意操作，应触发 GC（因为超过了时间间隔）
        await store.upsert_pending(
            request_id="req-002",
            request_type="group",
            chat_id=99999,
            location_name="触发GC",
            source_message="触发",
        )

        metrics = store.get_metrics()
        assert metrics["total_gc_runs"] > initial_gc_runs
        # 验证过期记录被清理
        assert metrics["total_expired_cleaned"] > 0


class TestMetrics:
    """测试性能指标"""

    @pytest.mark.asyncio
    async def test_metrics_tracking(self, store: InflightTaskStore) -> None:
        """测试性能指标追踪"""
        initial_metrics = store.get_metrics()

        # 创建占位
        await store.upsert_pending(
            request_id="req-001",
            request_type="group",
            chat_id=12345,
            location_name="测试群",
            source_message="测试消息",
        )

        # 标记就绪
        await store.mark_ready("req-001", "测试动作")

        # 查询
        await store.list_for_chat(request_type="group", chat_id=12345)

        # 清除
        await store.clear_by_request("req-001")

        metrics = store.get_metrics()

        assert metrics["total_upserts"] == initial_metrics["total_upserts"] + 1
        assert metrics["total_mark_ready"] == initial_metrics["total_mark_ready"] + 1
        assert metrics["total_queries"] == initial_metrics["total_queries"] + 1
        assert (
            metrics["anti_duplicate_hits"] == initial_metrics["anti_duplicate_hits"] + 1
        )
        assert metrics["total_clears"] == initial_metrics["total_clears"] + 1

    @pytest.mark.asyncio
    async def test_metrics_current_entries(self, store: InflightTaskStore) -> None:
        """测试当前记录数指标"""
        metrics = store.get_metrics()
        assert metrics["current_entries"] == 0

        # 创建 3 个占位
        for i in range(3):
            await store.upsert_pending(
                request_id=f"req-{i}",
                request_type="group",
                chat_id=i,
                location_name=f"群{i}",
                source_message=f"消息{i}",
            )

        metrics = store.get_metrics()
        assert metrics["current_entries"] == 3

        # 清除 1 个
        await store.clear_by_request("req-0")

        metrics = store.get_metrics()
        assert metrics["current_entries"] == 2


class TestEdgeCases:
    """测试边界情况"""

    @pytest.mark.asyncio
    async def test_empty_source_message(self, store: InflightTaskStore) -> None:
        """测试空消息"""
        record = await store.upsert_pending(
            request_id="req-001",
            request_type="group",
            chat_id=12345,
            location_name="测试群",
            source_message="",
        )

        assert record["source_message"] == "(无文本内容)"

    @pytest.mark.asyncio
    async def test_empty_location_name(self, store: InflightTaskStore) -> None:
        """测试空位置名称"""
        record = await store.upsert_pending(
            request_id="req-002",
            request_type="group",
            chat_id=12345,
            location_name="",
            source_message="测试消息",
        )

        assert record["location"]["name"] == "未知会话"

    @pytest.mark.asyncio
    async def test_empty_action_summary(self, store: InflightTaskStore) -> None:
        """测试空动作摘要"""
        await store.upsert_pending(
            request_id="req-003",
            request_type="group",
            chat_id=12345,
            location_name="测试群",
            source_message="测试消息",
        )

        success = await store.mark_ready("req-003", "")
        assert success is True

        records = await store.list_for_chat(request_type="group", chat_id=12345)
        assert "处理中" in records[0]["display_text"]

    @pytest.mark.asyncio
    async def test_whitespace_only_strings(self, store: InflightTaskStore) -> None:
        """测试仅包含空白字符的字符串"""
        record = await store.upsert_pending(
            request_id="  req-004  ",
            request_type="group",
            chat_id=12345,
            location_name="  测试群  ",
            source_message="  测试消息  ",
        )

        assert record["request_id"] == "req-004"
        assert record["location"]["name"] == "测试群"
        assert record["source_message"] == "测试消息"

    @pytest.mark.asyncio
    async def test_different_chat_types(self, store: InflightTaskStore) -> None:
        """测试不同会话类型的隔离"""
        # 群聊
        await store.upsert_pending(
            request_id="req-group",
            request_type="group",
            chat_id=12345,
            location_name="测试群",
            source_message="群聊消息",
        )

        # 私聊（相同 ID）
        await store.upsert_pending(
            request_id="req-private",
            request_type="private",
            chat_id=12345,
            location_name="测试用户",
            source_message="私聊消息",
        )

        # 查询群聊
        group_records = await store.list_for_chat(request_type="group", chat_id=12345)
        assert len(group_records) == 1
        assert group_records[0]["request_id"] == "req-group"

        # 查询私聊
        private_records = await store.list_for_chat(
            request_type="private", chat_id=12345
        )
        assert len(private_records) == 1
        assert private_records[0]["request_id"] == "req-private"
