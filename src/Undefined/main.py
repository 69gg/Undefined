"""程序入口"""

import asyncio
import logging
import signal
import time
import sys
from typing import Any
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler
from rich.console import Console

from Undefined.ai import AIClient
from Undefined.config import get_config, get_config_manager
from Undefined.config.hot_reload import HotReloadContext, apply_config_updates
from Undefined.config.loader import Config
from Undefined.context import RequestContextFilter
from Undefined.faq import FAQStorage
from Undefined.handlers import MessageHandler
from Undefined.memory import MemoryStorage
from Undefined.end_summary_storage import EndSummaryStorage
from Undefined.onebot import OneBotClient
from Undefined.api import RuntimeAPIContext, RuntimeAPIServer
from Undefined.token_usage_storage import TokenUsageStorage
from Undefined.weixin import WeixinService
from Undefined.utils.paths import (
    CACHE_DIR,
    DATA_DIR,
    DOWNLOAD_CACHE_DIR,
    IMAGE_CACHE_DIR,
    MEMES_BLOBS_DIR,
    MEMES_PREVIEWS_DIR,
    RENDER_CACHE_DIR,
    TEXT_FILE_CACHE_DIR,
    ensure_dir,
)

from Undefined.render import close_browser as close_render_browser
from Undefined.utils.render_cache import close_render_cache


def ensure_runtime_dirs() -> None:
    """确保运行时目录存在"""
    runtime_dirs = [
        DATA_DIR,
        Path("data/history"),
        Path("data/faq"),
        Path("data/scheduler_context"),
        CACHE_DIR,
        RENDER_CACHE_DIR,
        IMAGE_CACHE_DIR,
        DOWNLOAD_CACHE_DIR,
        TEXT_FILE_CACHE_DIR,
        MEMES_BLOBS_DIR,
        MEMES_PREVIEWS_DIR,
    ]
    for path in runtime_dirs:
        ensure_dir(path)


def setup_logging() -> None:
    """设置日志（控制台 + 文件轮转）"""
    config = Config.load(strict=False)
    level, log_level = _get_log_level(config)
    tty_active = bool(config.log_tty_enabled) and sys.stdout.isatty()

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 1. 控制台处理器
    if tty_active:
        _init_console_handler(root_logger, level)

    # 2. 文件处理器
    _init_file_handler(root_logger, config)

    logger = logging.getLogger(__name__)
    logger.info(
        "[启动] 日志系统初始化完成: level=%s file=%s max_bytes=%s backups=%s",
        log_level,
        config.log_file_path,
        config.log_max_size,
        config.log_backup_count,
    )
    logger.info(
        "[启动] 终端日志: enabled=%s active=%s",
        config.log_tty_enabled,
        tty_active,
    )


def _get_log_level(config: Config) -> tuple[int, str]:
    """从配置读取日志级别"""
    log_level = config.log_level.upper()
    level = getattr(logging, log_level, logging.INFO)
    return level, log_level


def _init_console_handler(root_logger: logging.Logger, level: int) -> None:
    """初始化控制台 Rich 日志处理器（开发态输出）"""
    console = Console(force_terminal=True)
    handler = RichHandler(
        level=level,
        console=console,
        show_time=True,
        show_path=True,
        markup=True,
        rich_tracebacks=True,
    )
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    root_logger.addHandler(handler)


def _init_file_handler(root_logger: logging.Logger, config: Config) -> None:
    """初始化文件轮转日志处理器（长期归档）"""
    log_file_path = config.log_file_path
    log_max_size = config.log_max_size
    log_backup_count = config.log_backup_count

    log_dir = Path(log_file_path).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    file_log_format = (
        "%(asctime)s [%(levelname)s] [%(request_id)s] %(name)s: %(message)s"
    )
    handler = RotatingFileHandler(
        log_file_path,
        maxBytes=log_max_size,
        backupCount=log_backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(file_log_format))
    handler.addFilter(RequestContextFilter())
    root_logger.addHandler(handler)


async def main() -> None:
    """主函数"""
    setup_logging()
    ensure_runtime_dirs()
    logger = logging.getLogger(__name__)
    logger.info("[启动] 正在初始化 Undefined 机器人...")

    start_time = time.perf_counter()
    try:
        did_compact = await TokenUsageStorage().compact_if_needed()
        elapsed = time.perf_counter() - start_time
        logger.info(
            "[Token统计] 启动归档检查完成: compacted=%s elapsed=%.3fs",
            did_compact,
            elapsed,
        )
    except Exception as exc:
        elapsed = time.perf_counter() - start_time
        logger.warning(
            "[Token统计] 启动时归档检查失败: error=%s elapsed=%.3fs",
            exc,
            elapsed,
        )

    try:
        config = get_config()
        logger.info("[配置] 配置加载成功")
        logger.info("[配置] 机器人 QQ: %s", config.bot_qq)
        logger.info("[配置] 超级管理员: %s", config.superadmin_qq)
        logger.info("[配置] 管理员 QQ 列表: %s", config.admin_qqs)
    except ValueError as exc:
        logger.error("[配置错误] 加载配置失败: %s", exc)
        sys.exit(1)

    # 初始化组件
    logger.info("[初始化] 正在加载核心组件...")
    cognitive_service = None
    historian_worker = None
    job_queue = None
    meme_service = None
    meme_worker = None
    meme_job_queue = None
    retrieval_registry = None
    runtime_api_server: RuntimeAPIServer | None = None
    weixin_service: WeixinService | None = None
    _reranker: Any = None
    try:
        init_start = time.perf_counter()
        onebot = OneBotClient(
            config.onebot_ws_url,
            config.onebot_token,
            config_getter=lambda: get_config(strict=False),
        )
        memory_storage = MemoryStorage(max_memories=100)
        end_summary_storage = EndSummaryStorage()
        ai = AIClient(
            config.chat_model,
            config.vision_model,
            config.agent_model,
            memory_storage,
            end_summary_storage,
            bot_qq=config.bot_qq,
            runtime_config=config,
        )
        await ai.attachment_registry.load()
        faq_storage = FAQStorage()
        from Undefined.config.models import EMBEDDING_FEATURES
        from Undefined.knowledge import RetrievalRuntimeRegistry

        retrieval_registry = RetrievalRuntimeRegistry(
            ai._requester,
            embedding_models={
                feature: config.resolve_embedding_model(feature)
                for feature in EMBEDDING_FEATURES
            },
            rerank_model=config.rerank_model,
            embed_batch_size=config.knowledge_embed_batch_size,
        )
        retrieval_runtime = retrieval_registry.for_feature("knowledge")
        cognitive_retrieval_runtime = retrieval_registry.for_feature("cognitive")
        meme_retrieval_runtime = retrieval_registry.for_feature("memes")

        # === Cognitive Memory ===
        cognitive_embedding = config.resolve_embedding_model("cognitive")
        cognitive_actually_enabled = config.cognitive.enabled
        if cognitive_actually_enabled and (
            not cognitive_embedding.api_url or not cognitive_embedding.model_name
        ):
            logger.warning(
                "[认知记忆] cognitive.enabled=true 但 models.embedding 未配置，自动降级禁用"
            )
            cognitive_actually_enabled = False

        cognitive_enable_rerank = bool(getattr(config.cognitive, "enable_rerank", True))
        need_reranker_for_knowledge = bool(
            config.knowledge_enabled and config.knowledge_enable_rerank
        )
        need_reranker_for_cognitive = bool(
            cognitive_actually_enabled and cognitive_enable_rerank
        )
        need_shared_reranker = (
            need_reranker_for_knowledge or need_reranker_for_cognitive
        )
        if need_shared_reranker:
            _reranker = retrieval_registry.ensure_reranker()
            if _reranker is None:
                if need_reranker_for_knowledge:
                    logger.warning(
                        "[知识库] 已启用重排，但 models.rerank 未配置完整，重排将自动禁用"
                    )
                if need_reranker_for_cognitive:
                    logger.warning(
                        "[认知记忆] 已启用重排，但 models.rerank 未配置完整，重排将自动禁用"
                    )

        if config.knowledge_enabled:
            from Undefined.knowledge import KnowledgeManager

            knowledge_embedding = config.resolve_embedding_model("knowledge")
            if not knowledge_embedding.api_url or not knowledge_embedding.model_name:
                raise ValueError(
                    "知识库已启用，但 models.embedding.api_url / model_name "
                    "（或 models.embedding.features.knowledge 覆写）未配置完整"
                )

            knowledge_manager = KnowledgeManager(
                base_dir=config.knowledge_base_dir,
                default_top_k=config.knowledge_default_top_k,
                chunk_size=config.knowledge_chunk_size,
                chunk_overlap=config.knowledge_chunk_overlap,
                rerank_enabled=config.knowledge_enable_rerank,
                rerank_top_k=config.knowledge_rerank_top_k,
                retrieval_runtime=retrieval_runtime,
            )
            ai.set_knowledge_manager(knowledge_manager)
            if config.knowledge_auto_scan and config.knowledge_auto_embed:
                knowledge_manager.start_auto_scan(config.knowledge_scan_interval)
            elif config.knowledge_auto_embed:
                knowledge_manager.start_initial_scan()
            logger.info("[知识库] 初始化完成: base_dir=%s", config.knowledge_base_dir)

        if cognitive_actually_enabled:
            from Undefined.cognitive import (
                CognitiveVectorStore,
                JobQueue,
                ProfileStorage,
                CognitiveService,
                HistorianWorker,
            )

            _cog_chroma = Path(config.cognitive.vector_store_path)
            _cog_queues = Path(config.cognitive.queue_path)
            _cog_profiles = Path(config.cognitive.profiles_path)

            for _cog_dir in (
                _cog_chroma,
                _cog_queues / "pending",
                _cog_queues / "processing",
                _cog_queues / "failed",
                _cog_profiles / "users",
                _cog_profiles / "groups",
                _cog_profiles / "history",
            ):
                ensure_dir(_cog_dir)

            vector_store = CognitiveVectorStore(
                str(_cog_chroma),
                cognitive_retrieval_runtime,
                scheduler_foreground_burst=config.cognitive.vector_store_scheduler_foreground_burst,
            )
            job_queue = JobQueue(str(_cog_queues))
            profile_storage = ProfileStorage(
                str(_cog_profiles),
                revision_keep=config.cognitive.profile_revision_keep,
            )
            cognitive_service = CognitiveService(
                config_getter=lambda: get_config(strict=False).cognitive,
                vector_store=vector_store,
                job_queue=job_queue,
                profile_storage=profile_storage,
                retrieval_runtime=cognitive_retrieval_runtime,
            )
            historian_worker = HistorianWorker(
                job_queue=job_queue,
                vector_store=vector_store,
                profile_storage=profile_storage,
                ai_client=ai,
                config_getter=lambda: get_config(strict=False).cognitive,
                model_config=config.historian_model,
                max_concurrency=config.cognitive.historian_max_concurrency,
            )
            ai.set_cognitive_service(cognitive_service)
            logger.info(
                "[认知记忆] 初始化完成: chroma_dir=%s queue_dir=%s profiles_dir=%s revision_keep=%s",
                str(_cog_chroma),
                str(_cog_queues),
                str(_cog_profiles),
                config.cognitive.profile_revision_keep,
            )

        if config.memes.enabled:
            from Undefined.cognitive import JobQueue
            from Undefined.memes import (
                MemeService,
                MemeStore,
                MemeVectorStore,
                MemeWorker,
            )

            meme_store = MemeStore(config.memes.db_path)
            meme_vector_store = MemeVectorStore(
                config.memes.vector_store_path,
                meme_retrieval_runtime,
            )
            meme_job_queue = JobQueue(config.memes.queue_path)
            meme_service = MemeService(
                config_getter=lambda: get_config(strict=False).memes,
                store=meme_store,
                vector_store=meme_vector_store,
                job_queue=meme_job_queue,
                ai_client=ai,
                attachment_registry=ai.attachment_registry,
                retrieval_runtime=meme_retrieval_runtime,
            )
            meme_worker = MemeWorker(
                job_queue=meme_job_queue,
                meme_service=meme_service,
                poll_interval_seconds=1.0,
                max_retries=3,
                max_concurrency=config.memes.worker_max_concurrency,
            )
            ai.set_meme_service(meme_service)
            logger.info(
                "[memes] 初始化完成: db=%s vector=%s queue=%s",
                config.memes.db_path,
                config.memes.vector_store_path,
                config.memes.queue_path,
            )

        handler = MessageHandler(config, onebot, ai, faq_storage)
        await handler.initialize()
        weixin_service = WeixinService(
            config,
            message_handler=handler,
            attachment_registry=ai.attachment_registry,
        )
        handler.sender.set_weixin_service(weixin_service)
        onebot.set_message_handler(handler.handle_message)
        elapsed = time.perf_counter() - init_start
        logger.info("[初始化] 核心组件加载完成: elapsed=%.3fs", elapsed)
    except Exception as exc:
        logger.exception("[初始化错误] 组件初始化期间发生异常: %s", exc)
        sys.exit(1)

    # Code Delivery Agent 残留清理（程序启动时执行一次）
    if config.code_delivery_enabled and config.code_delivery_cleanup_on_start:
        try:
            from Undefined.skills.agents.code_delivery_agent.handler import (
                _cleanup_residual,
            )

            await _cleanup_residual(
                config.code_delivery_task_root,
                config.code_delivery_container_name_prefix,
                config.code_delivery_container_name_suffix,
            )
            logger.info("[CodeDelivery] 启动残留清理完成")
        except Exception as exc:
            logger.warning("[CodeDelivery] 启动残留清理失败: %s", exc)

    logger.info("[启动] 机器人已准备就绪，开始连接 OneBot 服务...")

    if historian_worker and job_queue:
        recovered = await job_queue.recover_stale(
            timeout_seconds=config.cognitive.stale_job_timeout_seconds
        )
        logger.info(
            "[认知记忆] 启动前陈旧任务恢复完成: recovered=%s timeout_seconds=%s",
            recovered,
            config.cognitive.stale_job_timeout_seconds,
        )
        await historian_worker.start()
        logger.info("[认知记忆] 史官后台任务已启动")

    if meme_worker is not None:
        if meme_job_queue is not None:
            recovered = await meme_job_queue.recover_stale(timeout_seconds=300.0)
            logger.info("[memes] 启动前陈旧任务恢复完成: recovered=%s", recovered)
        await meme_worker.start()
        logger.info("[memes] 后台任务已启动")

    config_manager = get_config_manager()
    config_manager.load(strict=True)

    hot_reload_context = HotReloadContext(
        ai_client=ai,
        queue_manager=handler.queue_manager,
        config_manager=config_manager,
        security_service=handler.security,
        message_handler=handler,
    )

    def _apply_config_updates(
        updated: Config, changes: dict[str, tuple[object, object]]
    ) -> None:
        apply_config_updates(updated, changes, hot_reload_context)

    config_manager.subscribe(_apply_config_updates)
    config_manager.start_hot_reload(
        interval=config.skills_hot_reload_interval,
        debounce=config.skills_hot_reload_debounce,
    )
    logger.info(
        "[配置] 热更新监听已启动: interval=%.2fs debounce=%.2fs",
        config.skills_hot_reload_interval,
        config.skills_hot_reload_debounce,
    )

    if weixin_service is not None:
        await weixin_service.start()

    if config.api.enabled:
        # Naga 外部网关集成（需同时开启 nagaagent_mode_enabled 和 naga.enabled）
        naga_store = None
        if config.nagaagent_mode_enabled and config.naga.enabled:
            from Undefined.api.naga_store import NagaStore

            naga_store = NagaStore()
            await naga_store.load()
            handler.command_dispatcher.naga_store = naga_store
            logger.info("[Naga] 绑定存储已加载")

        runtime_api_context = RuntimeAPIContext(
            config_getter=lambda: get_config(strict=False),
            onebot=onebot,
            ai=ai,
            command_dispatcher=handler.command_dispatcher,
            queue_manager=handler.queue_manager,
            history_manager=handler.history_manager,
            sender=handler.sender,
            scheduler=handler.ai_coordinator.scheduler,
            cognitive_service=cognitive_service,
            cognitive_job_queue=job_queue,
            meme_service=meme_service,
            naga_store=naga_store,
            message_batcher=handler.message_batcher,
            pipeline_registry=handler.pipeline_registry,
            weixin_service=weixin_service,
        )
        runtime_api_server = RuntimeAPIServer(
            runtime_api_context,
            host=config.api.host,
            port=config.api.port,
        )
        try:
            await runtime_api_server.start()
            if config.api.auth_key == "changeme":
                logger.warning(
                    "[RuntimeAPI] 当前仍使用默认鉴权密钥 changeme，请尽快修改 [api].auth_key"
                )
        except Exception as exc:
            runtime_api_server = None
            logger.exception("[RuntimeAPI] 启动失败，已跳过: %s", exc)
    else:
        logger.info("[RuntimeAPI] 已禁用（api.enabled=false）")
        if config.nagaagent_mode_enabled and config.naga.enabled:
            logger.warning(
                "[Naga] 已启用 nagaagent_mode_enabled 与 naga.enabled，但 Runtime API 已关闭；"
                "/naga 命令和 /api/v1/naga/* 端点都不会可用"
            )

    shutdown_guard = install_shutdown_signal_handlers(logger)
    try:
        await _run_until_shutdown(onebot, shutdown_guard.event, logger)
    except KeyboardInterrupt:
        # 仅在信号处理器注册全部失败（如非主线程运行）时才会走到这里；
        # 正常安装后 SIGINT 会转为停机事件，不再抛 KeyboardInterrupt
        logger.info("[退出] 收到退出信号 (Ctrl+C)")
    except Exception as exc:
        logger.exception("[异常] 运行期间发生未捕获的错误: %s", exc)
    finally:
        logger.info("[清理] 正在关闭机器人并释放资源...")
        if runtime_api_server is not None:
            try:
                await runtime_api_server.stop()
            except Exception:
                logger.exception("[清理] RuntimeAPIServer stop 失败")
        if weixin_service is not None:
            try:
                await weixin_service.stop()
            except Exception:
                logger.exception("[清理] WeixinService stop 失败")
        try:
            await handler.close()
        except Exception:
            logger.exception("[清理] MessageHandler close 失败")
        if meme_worker is not None:
            await meme_worker.stop()
        if historian_worker:
            await historian_worker.stop()
        await onebot.disconnect()
        await ai.close()
        if retrieval_registry is not None:
            await retrieval_registry.stop()
        await config_manager.stop_hot_reload()
        await close_render_browser()
        await close_render_cache()
        shutdown_guard.restore()
        logger.info("[退出] 机器人已停止运行")


class ShutdownSignalGuard:
    """优雅停机信号注册的句柄：携带停机事件并支持恢复安装前的信号状态。"""

    def __init__(
        self,
        event: asyncio.Event,
        previous: dict[int, Any],
        loop_based: set[int],
        loop: asyncio.AbstractEventLoop,
        logger: logging.Logger,
    ) -> None:
        self.event = event
        self._previous = previous
        self._loop_based = loop_based
        self._loop = loop
        self._logger = logger

    def restore(self) -> None:
        """恢复安装前的信号处理器；须从安装时的同一线程调用。

        `remove_signal_handler` 与 `signal.signal` 分开捕获：循环已关闭时前者
        必然抛 RuntimeError，但不能因此跳过还原信号处理器的动作。
        """
        for signum, handler in self._previous.items():
            if signum in self._loop_based:
                try:
                    self._loop.remove_signal_handler(signum)
                except (OSError, RuntimeError, ValueError):
                    self._logger.debug(
                        "[退出] 卸载信号 %s 的事件循环处理器失败（循环可能已关闭）",
                        signum,
                    )
            try:
                signal.signal(signum, handler)
            except (OSError, ValueError):
                self._logger.warning("[退出] 恢复信号 %s 的原处理器失败", signum)
        self._previous.clear()


def install_shutdown_signal_handlers(logger: logging.Logger) -> ShutdownSignalGuard:
    """注册 SIGTERM / SIGINT 的优雅停机事件。

    容器与服务管理器默认发送 SIGTERM（而非 Ctrl+C 的 SIGINT），此前未处理会直接
    终止进程并跳过后面的落盘清理。这里把两个信号都收敛到同一个事件，由主循环在
    被唤醒后走正常关闭流程。

    安装前会保存原有处理器，停机完成后调用 `ShutdownSignalGuard.restore()`
    归还信号控制权，避免作为库被导入时永久劫持调用方的信号处理。
    """
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    previous: dict[int, Any] = {}
    loop_based: set[int] = set()
    for signame in ("SIGTERM", "SIGINT"):
        signum = getattr(signal, signame, None)
        if signum is None:
            continue
        try:
            previous[signum] = signal.getsignal(signum)
        except (OSError, ValueError):
            continue
        try:
            loop.add_signal_handler(signum, stop_event.set)
            loop_based.add(signum)
        except (NotImplementedError, RuntimeError, ValueError):
            # Windows 的事件循环不支持 add_signal_handler，退回到 signal.signal
            # add_signal_handler 可能已部分注册（改过 wakeup fd / handler），
            # 先尽力卸载，避免叠加两套处理器
            try:
                loop.remove_signal_handler(signum)
            except (NotImplementedError, RuntimeError, ValueError, OSError):
                pass
            try:
                signal.signal(
                    signum,
                    lambda *_args, _loop=loop, _event=stop_event: (
                        _loop.call_soon_threadsafe(_event.set)
                    ),
                )
            except (ValueError, OSError):
                logger.warning("[退出] 无法注册 %s 处理器", signame)
                # 未安装成功就没有需要恢复的状态
                previous.pop(signum, None)
    return ShutdownSignalGuard(stop_event, previous, loop_based, loop, logger)


async def _run_until_shutdown(
    onebot: OneBotClient,
    shutdown_event: asyncio.Event,
    logger: logging.Logger,
) -> None:
    """运行 OneBot 连接，收到停止信号或连接任务结束时返回。"""
    run_task = asyncio.create_task(onebot.run_with_reconnect(), name="onebot-run")
    stop_task = asyncio.create_task(shutdown_event.wait(), name="shutdown-wait")
    try:
        done, _pending = await asyncio.wait(
            {run_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if run_task in done:
            # 连接任务自行结束：把异常抛给上层处理
            run_task.result()
            return
        logger.info("[退出] 收到停止信号 (SIGTERM/SIGINT)，正在优雅停机...")
        run_task.cancel()
        try:
            await run_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("[退出] 停止 OneBot 连接时发生异常: %s", exc)
    finally:
        stop_task.cancel()
        try:
            await stop_task
        except asyncio.CancelledError:
            pass


def run() -> None:
    """运行入口"""
    asyncio.run(main())


if __name__ == "__main__":
    run()
