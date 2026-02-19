"""多模型池功能测试"""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from Undefined.ai.model_selector import ModelSelector
from Undefined.config.models import ChatModelConfig, ModelPool, ModelPoolEntry
from Undefined.services.model_pool import ModelPoolService


@pytest.fixture
def temp_preferences_path(tmp_path: Path) -> Path:
    """创建临时偏好文件路径"""
    return tmp_path / "model_preferences.json"


@pytest.fixture
def model_selector(temp_preferences_path: Path) -> ModelSelector:
    """创建测试用的 ModelSelector 实例"""
    return ModelSelector(
        preferences_path=temp_preferences_path,
        compare_expire_seconds=300,
    )


@pytest.fixture
def primary_chat_config() -> ChatModelConfig:
    """创建主模型配置"""
    pool = ModelPool(
        enabled=True,
        strategy="round_robin",
        models=[
            ModelPoolEntry(
                api_url="https://api.example.com/v1",
                api_key="key1",
                model_name="model-a",
                max_tokens=4096,
            ),
            ModelPoolEntry(
                api_url="https://api.example.com/v1",
                api_key="key2",
                model_name="model-b",
                max_tokens=4096,
            ),
        ],
    )
    return ChatModelConfig(
        api_url="https://api.example.com/v1",
        api_key="primary-key",
        model_name="primary-model",
        max_tokens=4096,
        pool=pool,
    )


@pytest.fixture
def mock_ai_client() -> MagicMock:
    """创建 mock AIClient"""
    ai = MagicMock()
    ai.request_model = AsyncMock()
    return ai


@pytest.fixture
def mock_config() -> MagicMock:
    """创建 mock Config"""
    config = MagicMock()
    config.model_pool_enabled = True
    return config


@pytest.fixture
def mock_sender() -> MagicMock:
    """创建 mock MessageSender"""
    sender = MagicMock()
    sender.send_private_message = AsyncMock()
    return sender


@pytest.fixture
def model_pool_service(
    mock_ai_client: MagicMock,
    mock_config: MagicMock,
    mock_sender: MagicMock,
    model_selector: ModelSelector,
) -> ModelPoolService:
    """创建 ModelPoolService 实例"""
    mock_ai_client.model_selector = model_selector
    return ModelPoolService(mock_ai_client, mock_config, mock_sender)


class TestModelSelectorCompare:
    """测试 ModelSelector 的 compare 相关功能"""

    def test_set_and_resolve_compare(self, model_selector: ModelSelector) -> None:
        """测试设置和解析 compare 状态"""
        user_id = 12345
        models = ["model-a", "model-b", "model-c"]

        model_selector.set_pending_compare(0, user_id, models)

        # 测试正确的选择
        result = model_selector.try_resolve_compare(0, user_id, "选1")
        assert result == "model-a"

        # 再次尝试应该失败（已消费）
        result = model_selector.try_resolve_compare(0, user_id, "选1")
        assert result is None

    def test_resolve_compare_with_spaces(self, model_selector: ModelSelector) -> None:
        """测试带空格的选择"""
        user_id = 12345
        models = ["model-a", "model-b"]

        model_selector.set_pending_compare(0, user_id, models)

        result = model_selector.try_resolve_compare(0, user_id, "选 2")
        assert result == "model-b"

    def test_resolve_compare_invalid_index(self, model_selector: ModelSelector) -> None:
        """测试无效的索引"""
        user_id = 12345
        models = ["model-a", "model-b"]

        model_selector.set_pending_compare(0, user_id, models)

        # 索引超出范围
        result = model_selector.try_resolve_compare(0, user_id, "选3")
        assert result is None

        # 索引为 0
        result = model_selector.try_resolve_compare(0, user_id, "选0")
        assert result is None

    def test_resolve_compare_invalid_format(
        self, model_selector: ModelSelector
    ) -> None:
        """测试无效的格式"""
        user_id = 12345
        models = ["model-a", "model-b"]

        model_selector.set_pending_compare(0, user_id, models)

        # 不匹配的格式
        result = model_selector.try_resolve_compare(0, user_id, "选择1")
        assert result is None

        result = model_selector.try_resolve_compare(0, user_id, "1")
        assert result is None

    @pytest.mark.asyncio
    async def test_compare_expiration(self, temp_preferences_path: Path) -> None:
        """测试 compare 状态过期"""
        selector = ModelSelector(
            preferences_path=temp_preferences_path,
            compare_expire_seconds=0.5,
        )

        user_id = 12345
        models = ["model-a", "model-b"]

        selector.set_pending_compare(0, user_id, models)

        # 立即解析应该成功
        result = selector.try_resolve_compare(0, user_id, "选1")
        assert result == "model-a"

        # 重新设置
        selector.set_pending_compare(0, user_id, models)

        # 等待过期
        await asyncio.sleep(0.6)

        # 过期后应该失败
        result = selector.try_resolve_compare(0, user_id, "选1")
        assert result is None


class TestModelSelectorPreference:
    """测试 ModelSelector 的偏好管理"""

    def test_set_and_get_preference(self, model_selector: ModelSelector) -> None:
        """测试设置和获取偏好"""
        user_id = 12345

        model_selector.set_preference(0, user_id, "chat", "model-a")

        result = model_selector.get_preference(0, user_id, "chat")
        assert result == "model-a"

    def test_clear_preference(self, model_selector: ModelSelector) -> None:
        """测试清除偏好"""
        user_id = 12345

        model_selector.set_preference(0, user_id, "chat", "model-a")
        model_selector.clear_preference(0, user_id, "chat")

        result = model_selector.get_preference(0, user_id, "chat")
        assert result is None

    def test_multiple_users_preferences(self, model_selector: ModelSelector) -> None:
        """测试多用户偏好隔离"""
        user1 = 12345
        user2 = 67890

        model_selector.set_preference(0, user1, "chat", "model-a")
        model_selector.set_preference(0, user2, "chat", "model-b")

        assert model_selector.get_preference(0, user1, "chat") == "model-a"
        assert model_selector.get_preference(0, user2, "chat") == "model-b"

    @pytest.mark.asyncio
    async def test_save_and_load_preferences(self, temp_preferences_path: Path) -> None:
        """测试偏好持久化"""
        selector1 = ModelSelector(preferences_path=temp_preferences_path)
        await selector1.load_preferences()

        selector1.set_preference(0, 12345, "chat", "model-a")
        selector1.set_preference(0, 67890, "chat", "model-b")
        await selector1.save_preferences()

        # 创建新实例加载
        selector2 = ModelSelector(preferences_path=temp_preferences_path)
        await selector2.load_preferences()

        assert selector2.get_preference(0, 12345, "chat") == "model-a"
        assert selector2.get_preference(0, 67890, "chat") == "model-b"


class TestModelSelectorSelection:
    """测试 ModelSelector 的模型选择逻辑"""

    def test_select_with_preference(
        self, model_selector: ModelSelector, primary_chat_config: ChatModelConfig
    ) -> None:
        """测试根据偏好选择模型"""
        user_id = 12345

        model_selector.set_preference(0, user_id, "chat", "model-a")

        result = model_selector.select_chat_config(
            primary_chat_config,
            group_id=0,
            user_id=user_id,
            global_enabled=True,
        )

        assert result.model_name == "model-a"

    def test_select_without_preference_round_robin(
        self, model_selector: ModelSelector, primary_chat_config: ChatModelConfig
    ) -> None:
        """测试无偏好时的轮询策略"""
        user1 = 12345
        user2 = 67890

        result1 = model_selector.select_chat_config(
            primary_chat_config, group_id=0, user_id=user1, global_enabled=True
        )
        result2 = model_selector.select_chat_config(
            primary_chat_config, group_id=0, user_id=user2, global_enabled=True
        )

        # 轮询应该选择不同的模型
        assert result1.model_name == "model-a"
        assert result2.model_name == "model-b"

    def test_select_with_disabled_pool(
        self, model_selector: ModelSelector, primary_chat_config: ChatModelConfig
    ) -> None:
        """测试池禁用时返回主模型"""
        user_id = 12345

        result = model_selector.select_chat_config(
            primary_chat_config,
            group_id=0,
            user_id=user_id,
            global_enabled=False,
        )

        assert result.model_name == "primary-model"

    def test_get_all_chat_models(
        self, model_selector: ModelSelector, primary_chat_config: ChatModelConfig
    ) -> None:
        """测试获取所有模型"""
        models = model_selector.get_all_chat_models(primary_chat_config)

        assert len(models) == 3
        assert models[0][0] == "primary-model"
        assert models[1][0] == "model-a"
        assert models[2][0] == "model-b"


class TestModelPoolServiceHandleMessage:
    """测试 ModelPoolService 的消息处理"""

    @pytest.mark.asyncio
    async def test_handle_compare_command(
        self,
        model_pool_service: ModelPoolService,
        mock_ai_client: MagicMock,
        mock_sender: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """测试处理 /compare 命令"""
        user_id = 12345
        mock_ai_client.request_model.return_value = {
            "choices": [{"message": {"content": "测试回复"}}]
        }
        mock_config.chat_model = ChatModelConfig(
            api_url="https://api.example.com/v1",
            api_key="key",
            model_name="primary-model",
            max_tokens=4096,
            pool=ModelPool(
                enabled=True,
                strategy="round_robin",
                models=[
                    ModelPoolEntry(
                        api_url="https://api.example.com/v1",
                        api_key="key1",
                        model_name="model-a",
                        max_tokens=4096,
                    ),
                ],
            ),
        )

        consumed = await model_pool_service.handle_private_message(
            user_id, "/compare 你好"
        )

        assert consumed is True
        assert mock_sender.send_private_message.call_count == 2
        assert mock_ai_client.request_model.call_count == 2

    @pytest.mark.asyncio
    async def test_handle_pk_command(
        self,
        model_pool_service: ModelPoolService,
        mock_ai_client: MagicMock,
        mock_sender: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """测试处理 /pk 命令"""
        user_id = 12345
        mock_ai_client.request_model.return_value = {
            "choices": [{"message": {"content": "测试回复"}}]
        }
        mock_config.chat_model = ChatModelConfig(
            api_url="https://api.example.com/v1",
            api_key="key",
            model_name="primary-model",
            max_tokens=4096,
            pool=ModelPool(
                enabled=True,
                strategy="round_robin",
                models=[
                    ModelPoolEntry(
                        api_url="https://api.example.com/v1",
                        api_key="key1",
                        model_name="model-a",
                        max_tokens=4096,
                    ),
                ],
            ),
        )

        consumed = await model_pool_service.handle_private_message(user_id, "/pk 你好")

        assert consumed is True
        assert mock_sender.send_private_message.call_count == 2

    @pytest.mark.asyncio
    async def test_handle_select_command(
        self,
        model_pool_service: ModelPoolService,
        model_selector: ModelSelector,
        mock_sender: MagicMock,
    ) -> None:
        """测试处理选择命令"""
        user_id = 12345

        model_selector.set_pending_compare(0, user_id, ["model-a", "model-b"])

        consumed = await model_pool_service.handle_private_message(user_id, "选1")

        assert consumed is True
        mock_sender.send_private_message.assert_called_once()
        assert "model-a" in mock_sender.send_private_message.call_args[0][1]
        assert model_selector.get_preference(0, user_id, "chat") == "model-a"

    @pytest.mark.asyncio
    async def test_handle_normal_message(
        self, model_pool_service: ModelPoolService
    ) -> None:
        """测试普通消息不被消费"""
        user_id = 12345

        consumed = await model_pool_service.handle_private_message(user_id, "你好")

        assert consumed is False

    @pytest.mark.asyncio
    async def test_handle_message_when_pool_disabled(
        self, model_pool_service: ModelPoolService, mock_config: MagicMock
    ) -> None:
        """测试池禁用时不处理消息"""
        mock_config.model_pool_enabled = False
        user_id = 12345

        consumed = await model_pool_service.handle_private_message(
            user_id, "/compare 你好"
        )

        assert consumed is False


class TestModelPoolServiceCompare:
    """测试 ModelPoolService 的 compare 功能"""

    @pytest.mark.asyncio
    async def test_compare_without_space(
        self, model_pool_service: ModelPoolService, mock_sender: MagicMock
    ) -> None:
        """测试 /compare 后面没有空格不会被识别"""
        user_id = 12345

        consumed = await model_pool_service.handle_private_message(user_id, "/compare")

        assert consumed is False
        mock_sender.send_private_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_compare_single_model(
        self,
        model_pool_service: ModelPoolService,
        mock_sender: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """测试只有一个模型时"""
        user_id = 12345
        mock_config.chat_model = ChatModelConfig(
            api_url="https://api.example.com/v1",
            api_key="key",
            model_name="primary-model",
            max_tokens=4096,
            pool=None,
        )

        consumed = await model_pool_service.handle_private_message(
            user_id, "/compare 你好"
        )

        assert consumed is True
        mock_sender.send_private_message.assert_called_once()
        assert "只有一个模型" in mock_sender.send_private_message.call_args[0][1]

    @pytest.mark.asyncio
    async def test_compare_with_error(
        self,
        model_pool_service: ModelPoolService,
        mock_ai_client: MagicMock,
        mock_sender: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """测试模型请求失败"""
        user_id = 12345
        mock_ai_client.request_model.side_effect = Exception("API 错误")
        mock_config.chat_model = ChatModelConfig(
            api_url="https://api.example.com/v1",
            api_key="key",
            model_name="primary-model",
            max_tokens=4096,
            pool=ModelPool(
                enabled=True,
                strategy="round_robin",
                models=[
                    ModelPoolEntry(
                        api_url="https://api.example.com/v1",
                        api_key="key1",
                        model_name="model-a",
                        max_tokens=4096,
                    ),
                ],
            ),
        )

        consumed = await model_pool_service.handle_private_message(
            user_id, "/compare 你好"
        )

        assert consumed is True
        assert mock_sender.send_private_message.call_count == 2
        final_message = mock_sender.send_private_message.call_args_list[1][0][1]
        assert "请求失败" in final_message

    @pytest.mark.asyncio
    async def test_compare_long_response_truncation(
        self,
        model_pool_service: ModelPoolService,
        mock_ai_client: MagicMock,
        mock_sender: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """测试长回复截断"""
        user_id = 12345
        long_content = "x" * 600
        mock_ai_client.request_model.return_value = {
            "choices": [{"message": {"content": long_content}}]
        }
        mock_config.chat_model = ChatModelConfig(
            api_url="https://api.example.com/v1",
            api_key="key",
            model_name="primary-model",
            max_tokens=4096,
            pool=ModelPool(
                enabled=True,
                strategy="round_robin",
                models=[
                    ModelPoolEntry(
                        api_url="https://api.example.com/v1",
                        api_key="key1",
                        model_name="model-a",
                        max_tokens=4096,
                    ),
                ],
            ),
        )

        consumed = await model_pool_service.handle_private_message(
            user_id, "/compare 你好"
        )

        assert consumed is True
        final_message = mock_sender.send_private_message.call_args_list[1][0][1]
        assert "..." in final_message


class TestModelPoolServiceSelectConfig:
    """测试 ModelPoolService 的模型配置选择"""

    def test_select_config_with_preference(
        self,
        model_pool_service: ModelPoolService,
        model_selector: ModelSelector,
        primary_chat_config: ChatModelConfig,
    ) -> None:
        """测试根据偏好选择配置"""
        user_id = 12345
        model_selector.set_preference(0, user_id, "chat", "model-a")

        result = model_pool_service.select_chat_config(primary_chat_config, user_id)

        assert result.model_name == "model-a"

    def test_select_config_without_preference(
        self,
        model_pool_service: ModelPoolService,
        primary_chat_config: ChatModelConfig,
    ) -> None:
        """测试无偏好时选择配置"""
        user_id = 12345

        result = model_pool_service.select_chat_config(primary_chat_config, user_id)

        assert result.model_name in ["model-a", "model-b"]


class TestModelPoolIntegration:
    """测试完整的 pk -> 选择 -> 分支深入流程"""

    @pytest.mark.asyncio
    async def test_full_workflow(
        self,
        model_pool_service: ModelPoolService,
        model_selector: ModelSelector,
        mock_ai_client: MagicMock,
        mock_sender: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """测试完整工作流：pk -> 选择 -> 后续对话使用选中模型"""
        user_id = 12345

        # 模拟两个模型的不同回复
        def mock_request(model_config: Any, **kwargs: Any) -> dict[str, Any]:
            if model_config.model_name == "primary-model":
                return {"choices": [{"message": {"content": "主模型回复"}}]}
            elif model_config.model_name == "model-a":
                return {"choices": [{"message": {"content": "模型A回复"}}]}
            else:
                return {"choices": [{"message": {"content": "模型B回复"}}]}

        mock_ai_client.request_model.side_effect = mock_request
        mock_config.chat_model = ChatModelConfig(
            api_url="https://api.example.com/v1",
            api_key="key",
            model_name="primary-model",
            max_tokens=4096,
            pool=ModelPool(
                enabled=True,
                strategy="round_robin",
                models=[
                    ModelPoolEntry(
                        api_url="https://api.example.com/v1",
                        api_key="key1",
                        model_name="model-a",
                        max_tokens=4096,
                    ),
                    ModelPoolEntry(
                        api_url="https://api.example.com/v1",
                        api_key="key2",
                        model_name="model-b",
                        max_tokens=4096,
                    ),
                ],
            ),
        )

        # 步骤1: 执行 pk
        consumed = await model_pool_service.handle_private_message(user_id, "/pk 你好")
        assert consumed is True
        assert mock_ai_client.request_model.call_count == 3

        # 验证 compare 状态已设置
        final_message = mock_sender.send_private_message.call_args_list[1][0][1]
        assert "【1】primary-model" in final_message
        assert "【2】model-a" in final_message
        assert "【3】model-b" in final_message
        assert "选X" in final_message

        # 步骤2: 选择模型A
        mock_sender.reset_mock()
        consumed = await model_pool_service.handle_private_message(user_id, "选2")
        assert consumed is True
        mock_sender.send_private_message.assert_called_once()
        assert "model-a" in mock_sender.send_private_message.call_args[0][1]

        # 验证偏好已设置
        assert model_selector.get_preference(0, user_id, "chat") == "model-a"

        # 步骤3: 后续对话应使用选中的模型
        result = model_pool_service.select_chat_config(mock_config.chat_model, user_id)
        assert result.model_name == "model-a"

    @pytest.mark.asyncio
    async def test_multiple_users_isolation(
        self,
        model_pool_service: ModelPoolService,
        model_selector: ModelSelector,
        mock_ai_client: MagicMock,
        mock_sender: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """测试多用户隔离"""
        user1 = 12345
        user2 = 67890

        mock_ai_client.request_model.return_value = {
            "choices": [{"message": {"content": "测试回复"}}]
        }
        mock_config.chat_model = ChatModelConfig(
            api_url="https://api.example.com/v1",
            api_key="key",
            model_name="primary-model",
            max_tokens=4096,
            pool=ModelPool(
                enabled=True,
                strategy="round_robin",
                models=[
                    ModelPoolEntry(
                        api_url="https://api.example.com/v1",
                        api_key="key1",
                        model_name="model-a",
                        max_tokens=4096,
                    ),
                    ModelPoolEntry(
                        api_url="https://api.example.com/v1",
                        api_key="key2",
                        model_name="model-b",
                        max_tokens=4096,
                    ),
                ],
            ),
        )

        # 用户1 执行 pk
        await model_pool_service.handle_private_message(user1, "/pk 问题1")
        model_selector.set_pending_compare(0, user1, ["model-a", "model-b"])

        # 用户2 执行 pk
        await model_pool_service.handle_private_message(user2, "/pk 问题2")
        model_selector.set_pending_compare(0, user2, ["model-a", "model-b"])

        # 用户1 选择 model-a
        await model_pool_service.handle_private_message(user1, "选1")

        # 用户2 选择 model-b
        await model_pool_service.handle_private_message(user2, "选2")

        # 验证偏好隔离
        assert model_selector.get_preference(0, user1, "chat") == "model-a"
        assert model_selector.get_preference(0, user2, "chat") == "model-b"

        # 验证后续对话使用各自的模型
        result1 = model_pool_service.select_chat_config(mock_config.chat_model, user1)
        result2 = model_pool_service.select_chat_config(mock_config.chat_model, user2)

        assert result1.model_name == "model-a"
        assert result2.model_name == "model-b"


class TestModelSelectorBugFixes:
    """测试模型选择器的 bug 修复"""

    def test_clear_invalid_preference_when_model_removed(
        self, model_selector: ModelSelector, primary_chat_config: ChatModelConfig
    ) -> None:
        """测试当用户偏好的模型从池中移除时，偏好被自动清除"""
        user_id = 12345

        # 设置用户偏好为 model-a
        model_selector.set_preference(0, user_id, "chat", "model-a")
        assert model_selector.get_preference(0, user_id, "chat") == "model-a"

        # 创建一个新的配置，池中不包含 model-a
        new_pool = ModelPool(
            enabled=True,
            strategy="round_robin",
            models=[
                ModelPoolEntry(
                    api_url="https://api.example.com/v1",
                    api_key="key2",
                    model_name="model-b",
                    max_tokens=4096,
                ),
            ],
        )
        new_config = ChatModelConfig(
            api_url="https://api.example.com/v1",
            api_key="primary-key",
            model_name="primary-model",
            max_tokens=4096,
            pool=new_pool,
        )

        # 选择模型时，由于 model-a 不在池中，应该清除偏好并回退到策略选择
        result = model_selector.select_chat_config(
            new_config, group_id=0, user_id=user_id, global_enabled=True
        )

        # 验证偏好已被清除
        assert model_selector.get_preference(0, user_id, "chat") is None
        # 验证回退到策略选择（round_robin 第一个模型）
        assert result.model_name == "model-b"

    @pytest.mark.asyncio
    async def test_round_robin_thread_safety(
        self, model_selector: ModelSelector, primary_chat_config: ChatModelConfig
    ) -> None:
        """测试 round-robin 计数器在并发场景下的线程安全"""
        import concurrent.futures

        # 并发选择模型 100 次
        def select_model() -> str:
            result = model_selector.select_chat_config(
                primary_chat_config, group_id=0, user_id=0, global_enabled=True
            )
            return result.model_name

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(select_model) for _ in range(100)]
            results = [f.result() for f in futures]

        # 验证所有选择都成功（没有异常）
        assert len(results) == 100
        # 验证 round-robin 轮询（model-a 和 model-b 应该大致各占一半）
        count_a = results.count("model-a")
        count_b = results.count("model-b")
        assert count_a == 50
        assert count_b == 50

    def test_get_all_chat_models_no_duplicate_primary(
        self, model_selector: ModelSelector
    ) -> None:
        """测试 get_all_chat_models 不会重复包含主模型"""
        # 创建一个配置，池中包含与主模型同名的模型
        pool = ModelPool(
            enabled=True,
            strategy="round_robin",
            models=[
                ModelPoolEntry(
                    api_url="https://api.example.com/v1",
                    api_key="key1",
                    model_name="primary-model",  # 与主模型同名
                    max_tokens=4096,
                ),
                ModelPoolEntry(
                    api_url="https://api.example.com/v1",
                    api_key="key2",
                    model_name="model-b",
                    max_tokens=4096,
                ),
            ],
        )
        config = ChatModelConfig(
            api_url="https://api.example.com/v1",
            api_key="primary-key",
            model_name="primary-model",
            max_tokens=4096,
            pool=pool,
        )

        # 获取所有模型
        all_models = model_selector.get_all_chat_models(config)

        # 验证主模型只出现一次
        model_names = [name for name, _ in all_models]
        assert model_names.count("primary-model") == 1
        # 验证总共有 2 个模型（primary-model 和 model-b）
        assert len(all_models) == 2
        assert set(model_names) == {"primary-model", "model-b"}
