"""Stats（/stats）命令实现：统计汇总、图表绘制与私聊投递。

从 `services/command.py` 拆出，作为 `CommandDispatcher` 的 mixin；
绘图依赖 matplotlib（必需依赖），相关常量也随实现一起迁移。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4
from collections.abc import Awaitable, Callable

import matplotlib.pyplot as plt

from Undefined.ai.queue_budget import (
    compute_queued_llm_timeout_seconds,
    resolve_effective_retry_count,
)
from Undefined.services.commands.context import PrivateForwardCallback
from Undefined.utils import io
from Undefined.utils.paths import RENDER_CACHE_DIR
from Undefined.utils.sender import is_definitive_weixin_delivery_rejection

if TYPE_CHECKING:
    from Undefined.ai import AIClient
    from Undefined.config import Config
    from Undefined.faq import FAQStorage
    from Undefined.onebot import OneBotClient
    from Undefined.services.commands.registry import CommandRegistry
    from Undefined.token_usage_storage import TokenUsageStorage
    from Undefined.utils.history import MessageHistoryManager
    from Undefined.services.queue_manager import QueueManager
    from Undefined.utils.sender import MessageSender

logger = logging.getLogger(__name__)

_STATS_DEFAULT_DAYS = 7
_STATS_MIN_DAYS = 1
_STATS_MAX_DAYS = 365
_STATS_MODEL_TOP_N = 8
_STATS_CALL_TYPE_TOP_N = 12
_STATS_DATA_SUMMARY_MAX_CHARS = 12000
_STATS_AI_FLAGS = {"--ai", "-a"}
_STATS_TIME_RANGE_RE = re.compile(r"^\d+[dwm]?$", re.IGNORECASE)


class StatsCommandMixin:
    """`/stats` 命令的统计、绘图与投递实现。"""

    if TYPE_CHECKING:
        config: Config
        ai: AIClient
        sender: MessageSender
        onebot: OneBotClient
        faq_storage: FAQStorage
        command_registry: CommandRegistry
        history_manager: MessageHistoryManager
        queue_manager: QueueManager
        _token_usage_storage: TokenUsageStorage
        _stats_analysis_results: dict[str, str]
        _stats_analysis_events: dict[str, asyncio.Event]
        _stats_render_lock: asyncio.Lock

    def _parse_time_range(self, time_str: str) -> int:
        """解析时间范围字符串，返回天数

        参数:
            time_str: 时间范围字符串（如 "7d", "1w", "30d"）

        返回:
            天数
        """
        if not time_str:
            return _STATS_DEFAULT_DAYS

        def _clamp_days(value: int) -> int:
            if value < _STATS_MIN_DAYS:
                return _STATS_DEFAULT_DAYS
            if value > _STATS_MAX_DAYS:
                return _STATS_MAX_DAYS
            return value

        time_str = time_str.lower().strip()

        # 解析快捷格式
        if time_str.endswith("d"):
            try:
                return _clamp_days(int(time_str[:-1]))
            except ValueError:
                return _STATS_DEFAULT_DAYS
        elif time_str.endswith("w"):
            try:
                return _clamp_days(int(time_str[:-1]) * 7)
            except ValueError:
                return _STATS_DEFAULT_DAYS
        elif time_str.endswith("m"):
            try:
                return _clamp_days(int(time_str[:-1]) * 30)
            except ValueError:
                return _STATS_DEFAULT_DAYS

        # 尝试直接解析为数字（默认为天）
        try:
            return _clamp_days(int(time_str))
        except ValueError:
            return _STATS_DEFAULT_DAYS

    def _parse_stats_options(self, args: list[str]) -> tuple[int, bool]:
        """解析 /stats 参数：时间范围 + AI 分析开关。"""
        days = _STATS_DEFAULT_DAYS
        enable_ai_analysis = False
        picked_days = False

        for raw in args:
            token = str(raw or "").strip()
            if not token:
                continue
            lower = token.lower()
            if lower in _STATS_AI_FLAGS:
                enable_ai_analysis = True
                continue
            if not picked_days and _STATS_TIME_RANGE_RE.match(lower):
                days = self._parse_time_range(lower)
                picked_days = True

        return days, enable_ai_analysis

    async def handle_stats(
        self, group_id: int, sender_id: int, args: list[str]
    ) -> None:
        """处理 /stats 命令，生成 token 使用统计图表（可选 AI 分析）"""
        days, enable_ai_analysis = self._parse_stats_options(args)
        img_dir: Path | None = None
        try:
            summary = await self._token_usage_storage.get_summary(days=days)
            if summary["total_calls"] == 0:
                await self.sender.send_group_message(
                    group_id, f"📊 最近 {days} 天内无 Token 使用记录。"
                )
                return

            ai_analysis = ""
            if enable_ai_analysis:
                ai_analysis = await self._run_stats_ai_analysis(
                    scope="group",
                    scope_id=group_id,
                    sender_id=sender_id,
                    summary=summary,
                    days=days,
                )

            img_dir = await self._create_stats_render_dir()
            await self._generate_stats_charts(summary, img_dir, days)

            forward_messages = await self._build_stats_forward_nodes(
                summary, img_dir, days, ai_analysis
            )
            await self._send_group_forward_message(
                group_id,
                forward_messages,
                history_message=self._build_stats_history_message(
                    summary,
                    days,
                    ai_analysis,
                ),
            )

        except Exception as e:
            error_id = uuid4().hex[:8]
            logger.exception(
                "[Stats] 生成统计图表失败: error_id=%s err=%s", error_id, e
            )
            await self.sender.send_group_message(
                group_id,
                f"❌ 生成统计图表失败，请稍后重试（错误码: {error_id}）",
            )
        finally:
            if img_dir is not None:
                await io.delete_tree(img_dir)

    async def _send_group_forward_message(
        self,
        group_id: int,
        messages: list[dict[str, Any]],
        *,
        history_message: str,
    ) -> None:
        send_forward = getattr(self.sender, "send_group_forward_message", None)
        if callable(send_forward):
            await send_forward(group_id, messages, history_message=history_message)
            return

        await self.onebot.send_forward_msg(group_id, messages)
        if self.history_manager is None:
            return
        text_content = history_message.strip()
        if not text_content:
            return
        await self.history_manager.add_group_message(
            group_id=group_id,
            sender_id=getattr(self.config, "bot_qq", 0),
            text_content=text_content,
            sender_nickname="Bot",
            group_name="",
        )

    @staticmethod
    def _build_stats_history_message(
        summary: dict[str, Any],
        days: int,
        ai_analysis: str,
    ) -> str:
        lines = [
            f"[命令输出] /stats 最近 {days} 天 Token 使用统计",
            f"总调用: {summary.get('total_calls', 0)}",
            f"总 Token: {summary.get('total_tokens', 0)}",
            f"输入 Token: {summary.get('prompt_tokens', 0)}",
            f"输出 Token: {summary.get('completion_tokens', 0)}",
        ]
        if ai_analysis.strip():
            lines.extend(["", "AI 分析:", ai_analysis.strip()])
        return "\n".join(lines)

    async def handle_stats_private(
        self,
        user_id: int,
        sender_id: int,
        args: list[str],
        send_message: Callable[[str], Awaitable[None]] | None = None,
        send_forward: PrivateForwardCallback | None = None,
        *,
        is_webui_session: bool = False,
    ) -> None:
        """处理私聊 /stats（含 WebUI 虚拟私聊适配）。"""

        async def _send_private(message: str) -> None:
            if send_message is not None:
                await send_message(message)
            else:
                await self.sender.send_private_message(user_id, message)

        days, enable_ai_analysis = self._parse_stats_options(args)
        img_dir: Path | None = None
        try:
            summary = await self._token_usage_storage.get_summary(days=days)
            if summary["total_calls"] == 0:
                await _send_private(f"📊 最近 {days} 天内无 Token 使用记录。")
                return

            ai_analysis = ""
            if enable_ai_analysis:
                ai_analysis = await self._run_stats_ai_analysis(
                    scope="private",
                    scope_id=0,
                    sender_id=sender_id,
                    summary=summary,
                    days=days,
                )

            img_dir = await self._create_stats_render_dir()
            await self._generate_stats_charts(summary, img_dir, days)

            if send_forward is not None:
                nodes = await self._build_stats_forward_nodes(
                    summary,
                    img_dir,
                    days,
                    ai_analysis,
                )
                try:
                    await send_forward(
                        user_id,
                        nodes,
                        history_message=self._build_stats_history_message(
                            summary,
                            days,
                            ai_analysis,
                        ),
                    )
                except Exception as exc:
                    if not is_definitive_weixin_delivery_rejection(exc):
                        logger.exception(
                            "[Stats] 私聊图表投递结果不确定，不执行二次发送: "
                            "user=%s err=%s",
                            user_id,
                            exc,
                        )
                        return
                    logger.exception(
                        "[Stats] 私聊图表投递失败，回退文本摘要: user=%s err=%s",
                        user_id,
                        exc,
                    )
                    fallback = self._build_stats_summary_text(summary)
                    if ai_analysis:
                        fallback += f"\n\n🤖 AI 智能分析\n{ai_analysis}"
                    fallback += "\n\n⚠️ 图表发送失败，已保留统计摘要。"
                    await _send_private(fallback)
                return

            await _send_private(f"📊 最近 {days} 天的 Token 使用统计：")
            for img_name in ["line_chart", "bar_chart", "pie_chart", "table"]:
                img_path = img_dir / f"stats_{img_name}.png"
                if await io.is_file(img_path):
                    message = await self.build_private_stats_image_message(
                        img_path,
                        inline_base64=is_webui_session,
                    )
                    await _send_private(message)

            await _send_private(self._build_stats_summary_text(summary))
            if ai_analysis:
                await _send_private(f"🤖 AI 智能分析\n{ai_analysis}")
        except Exception as e:
            error_id = uuid4().hex[:8]
            logger.exception(
                "[Stats] 私聊统计生成失败: error_id=%s user=%s err=%s",
                error_id,
                user_id,
                e,
            )
            await _send_private(
                f"❌ 生成统计图表失败，请稍后重试（错误码: {error_id}）"
            )
        finally:
            if img_dir is not None:
                await io.delete_tree(img_dir)

    async def build_private_stats_image_message(
        self,
        image_path: Path,
        *,
        inline_base64: bool,
    ) -> str:
        file_uri = image_path.absolute().as_uri()
        if not inline_base64:
            return f"[CQ:image,file={file_uri}]"

        try:
            content = await io.read_bytes(image_path)
            encoded = base64.b64encode(content).decode("ascii")
        except Exception as exc:
            logger.warning(
                "[Stats] 图像 base64 编码失败，回退文件路径: path=%s err=%s",
                file_uri,
                exc,
            )
            return f"[CQ:image,file={file_uri}]"

        return f"[CQ:image,file=base64://{encoded}]"

    async def _run_stats_ai_analysis(
        self,
        *,
        scope: str,
        scope_id: int,
        sender_id: int,
        summary: dict[str, Any],
        days: int,
    ) -> str:
        if not self.queue_manager:
            return ""

        data_summary = self._build_data_summary(summary, days)
        request_id = uuid4().hex
        analysis_event = asyncio.Event()
        self._stats_analysis_events[request_id] = analysis_event
        request_data = {
            "type": "stats_analysis",
            "group_id": scope_id,
            "request_id": request_id,
            "sender_id": sender_id,
            "data_summary": data_summary,
            "summary": summary,
            "days": days,
            "scope": scope,
        }
        receipt = await self.queue_manager.add_group_mention_request(
            request_data, model_name=self.config.chat_model.model_name
        )
        logger.info("[Stats] 已投递 AI 分析请求: scope=%s target=%s", scope, scope_id)

        wait_timeout = compute_queued_llm_timeout_seconds(
            self.ai.runtime_config,
            self.config.chat_model,
            retry_count=resolve_effective_retry_count(
                self.ai.runtime_config, self.queue_manager
            ),
            initial_wait_seconds=float(
                getattr(receipt, "estimated_wait_seconds", 0.0) or 0.0
            ),
        )
        try:
            await asyncio.wait_for(analysis_event.wait(), timeout=wait_timeout)
            ai_analysis = self._stats_analysis_results.pop(request_id, "")
            logger.info(
                "[Stats] 已获取 AI 分析结果: scope=%s len=%s", scope, len(ai_analysis)
            )
            return ai_analysis
        except asyncio.TimeoutError:
            logger.warning(
                "[Stats] AI 分析超时: scope=%s target=%s timeout=%.1fs",
                scope,
                scope_id,
                wait_timeout,
            )
            return "AI 分析在当前动态等待期限内超时。"
        finally:
            self._stats_analysis_events.pop(request_id, None)
            self._stats_analysis_results.pop(request_id, None)

    def _build_data_summary(self, summary: dict[str, Any], days: int) -> str:
        """构建用于 AI 分析的统计数据摘要"""
        lines = []
        lines.append("📊 Token 使用综合分析数据：")
        lines.append("")

        # 整体概况
        lines.append("【整体概况】")
        lines.append(f"统计周期: {days} 天")
        lines.append(f"总调用次数: {summary['total_calls']}")
        lines.append(f"总 Token 消耗: {summary['total_tokens']:,}")
        lines.append(f"平均响应时间: {summary['avg_duration']:.2f}s")
        lines.append(f"涉及模型数: {len(summary['models'])}")
        lines.append("")

        # 时间维度
        daily_stats = summary.get("daily_stats", {})
        if daily_stats:
            dates = sorted(daily_stats.keys())
            total_daily_calls = sum(daily_stats[d]["calls"] for d in dates)
            total_daily_tokens = sum(daily_stats[d]["tokens"] for d in dates)
            avg_daily_calls = total_daily_calls / len(dates) if dates else 0
            avg_daily_tokens = total_daily_tokens / len(dates) if dates else 0

            # 找出高峰日
            peak_day = (
                max(dates, key=lambda d: daily_stats[d]["tokens"]) if dates else ""
            )
            peak_day_tokens = daily_stats[peak_day]["tokens"] if peak_day else 0

            lines.append("【时间维度】")
            lines.append(f"统计天数: {len(dates)} 天")
            lines.append(f"每日平均调用: {avg_daily_calls:.1f} 次")
            lines.append(f"每日平均 Token: {avg_daily_tokens:,.0f} 个")
            lines.append(f"高峰日期: {peak_day} ({peak_day_tokens:,} tokens)")
            lines.append("")

        # 模型维度
        models = summary.get("models", {})
        if models:
            lines.append("【模型维度】")
            total_tokens_all = summary["total_tokens"]
            sorted_models = sorted(
                models.items(), key=lambda x: x[1]["tokens"], reverse=True
            )
            for model_name, model_data in sorted_models[:_STATS_MODEL_TOP_N]:
                calls = model_data["calls"]
                tokens = model_data["tokens"]
                prompt_tokens = model_data["prompt_tokens"]
                completion_tokens = model_data["completion_tokens"]
                token_pct = (
                    (tokens / total_tokens_all * 100) if total_tokens_all > 0 else 0
                )
                avg_per_call = tokens / calls if calls > 0 else 0
                io_ratio = completion_tokens / prompt_tokens if prompt_tokens > 0 else 0

                lines.append(f"模型: {model_name}")
                lines.append(
                    f"  - 调用次数: {calls} ({calls / summary['total_calls'] * 100:.1f}%)"
                )
                lines.append(f"  - Token 消耗: {tokens:,} ({token_pct:.1f}%)")
                lines.append(f"  - 平均每次调用: {avg_per_call:.0f} tokens")
                lines.append(
                    f"  - 输入: {prompt_tokens:,} / 输出: {completion_tokens:,}"
                )
                lines.append(f"  - 输入/输出比: 1:{io_ratio:.2f}")
                lines.append("")

            if len(sorted_models) > _STATS_MODEL_TOP_N:
                others = sorted_models[_STATS_MODEL_TOP_N:]
                others_calls = sum(int(item[1].get("calls", 0)) for item in others)
                others_tokens = sum(int(item[1].get("tokens", 0)) for item in others)
                others_pct = (
                    (others_tokens / total_tokens_all * 100)
                    if total_tokens_all > 0
                    else 0.0
                )
                lines.append(
                    f"其余 {len(others)} 个模型合计: 调用 {others_calls} 次, Token {others_tokens:,} ({others_pct:.1f}%)"
                )
                lines.append("")

        # 调用类型维度
        call_types = summary.get("call_types", {})
        if call_types:
            lines.append("【调用类型维度】")
            sorted_types = sorted(
                call_types.items(), key=lambda item: int(item[1]), reverse=True
            )
            total_calls = max(1, int(summary.get("total_calls", 0)))
            for call_type, count in sorted_types[:_STATS_CALL_TYPE_TOP_N]:
                ratio = int(count) / total_calls * 100
                lines.append(f"- {call_type}: {count} 次 ({ratio:.1f}%)")
            if len(sorted_types) > _STATS_CALL_TYPE_TOP_N:
                rest_count = sum(
                    int(item[1]) for item in sorted_types[_STATS_CALL_TYPE_TOP_N:]
                )
                ratio = rest_count / total_calls * 100
                lines.append(
                    f"- 其他 {len(sorted_types) - _STATS_CALL_TYPE_TOP_N} 类: {rest_count} 次 ({ratio:.1f}%)"
                )
            lines.append("")

        # 效率指标
        prompt_tokens = summary.get("prompt_tokens", 0)
        completion_tokens = summary.get("completion_tokens", 0)
        total_tokens = summary.get("total_tokens", 0)
        input_ratio = (prompt_tokens / total_tokens * 100) if total_tokens > 0 else 0
        output_ratio = (
            (completion_tokens / total_tokens * 100) if total_tokens > 0 else 0
        )
        output_per_input = completion_tokens / prompt_tokens if prompt_tokens > 0 else 0

        lines.append("【效率指标】")
        lines.append(f"输入 Token: {prompt_tokens:,} ({input_ratio:.1f}%)")
        lines.append(f"输出 Token: {completion_tokens:,} ({output_ratio:.1f}%)")
        lines.append(f"输入/输出比: 1:{output_per_input:.2f}")
        lines.append("")

        # 趋势分析
        if daily_stats and len(daily_stats) > 1:
            lines.append("【趋势分析】")
            dates = sorted(daily_stats.keys())
            first_day_tokens = daily_stats[dates[0]]["tokens"]
            last_day_tokens = daily_stats[dates[-1]]["tokens"]
            trend_change = (
                ((last_day_tokens - first_day_tokens) / first_day_tokens * 100)
                if first_day_tokens > 0
                else 0
            )
            trend_desc = "增长" if trend_change > 0 else "下降"
            lines.append(
                f"总体趋势: {trend_desc} {abs(trend_change):.1f}% (从首日到末日)"
            )
            lines.append("")

        summary_text = "\n".join(lines)
        if len(summary_text) > _STATS_DATA_SUMMARY_MAX_CHARS:
            trimmed = summary_text[: _STATS_DATA_SUMMARY_MAX_CHARS - 80].rstrip()
            summary_text = (
                f"{trimmed}\n\n[数据摘要已截断，总长度 {len(summary_text)} 字符，"
                f"仅保留前 {_STATS_DATA_SUMMARY_MAX_CHARS} 字符]"
            )
            logger.info(
                "[Stats] 数据摘要过长已截断: original_len=%s max_len=%s",
                len("\n".join(lines)),
                _STATS_DATA_SUMMARY_MAX_CHARS,
            )
        return summary_text

    def _build_stats_summary_text(self, summary: dict[str, Any]) -> str:
        return f"""📈 摘要汇总:
    • 总调用次数: {summary["total_calls"]}
    • 总消耗 Tokens: {summary["total_tokens"]:,}
      └─ 输入: {summary["prompt_tokens"]:,}
      └─ 输出: {summary["completion_tokens"]:,}
    • 平均耗时: {summary["avg_duration"]:.2f}s
    • 涉及模型数: {len(summary["models"])}"""

    def set_stats_analysis_result(
        self, group_id: int, request_id: str, analysis: str
    ) -> None:
        """设置 AI 分析结果（由队列处理器调用）"""
        event = self._stats_analysis_events.get(request_id)
        if not event:
            logger.warning(
                "[StatsAnalysis] 未找到等待事件，群: %s, 请求: %s",
                group_id,
                request_id,
            )
            return
        self._stats_analysis_results[request_id] = analysis
        event.set()

    async def _create_stats_render_dir(self) -> Path:

        base_dir = await io.ensure_dir(RENDER_CACHE_DIR)
        return await io.ensure_dir(base_dir / f"stats_{uuid4().hex}")

    async def _generate_stats_charts(
        self,
        summary: dict[str, Any],
        img_dir: Path,
        days: int,
    ) -> None:
        async with self._stats_render_lock:
            await asyncio.to_thread(
                self._generate_stats_charts_sync,
                summary,
                img_dir,
                days,
            )

    def _generate_stats_charts_sync(
        self,
        summary: dict[str, Any],
        img_dir: Path,
        days: int,
    ) -> None:
        self._generate_line_chart(summary, img_dir, days)
        self._generate_bar_chart(summary, img_dir)
        self._generate_pie_chart(summary, img_dir)
        self._generate_stats_table(summary, img_dir)

    async def _build_stats_forward_nodes(
        self,
        summary: dict[str, Any],
        img_dir: Path,
        days: int,
        ai_analysis: str = "",
    ) -> list[dict[str, Any]]:
        """构建用于合并转发的统计图表节点列表"""
        nodes = []
        bot_qq = str(self.config.bot_qq)

        # 辅助函数：创建消息节点
        def add_node(content: str) -> None:
            nodes.append(
                {
                    "type": "node",
                    "data": {"name": "Bot", "uin": bot_qq, "content": content},
                }
            )

        add_node(f"📊 最近 {days} 天的 Token 使用统计：")

        # 添加所有生成的图片
        for img_name in ["line_chart", "bar_chart", "pie_chart", "table"]:
            img_path = img_dir / f"stats_{img_name}.png"
            if await io.is_file(img_path):
                add_node(f"[CQ:image,file={img_path.absolute().as_uri()}]")

        # 添加文本摘要
        add_node(self._build_stats_summary_text(summary))

        # 添加 AI 分析结果（如果有）
        if ai_analysis:
            add_node(f"🤖 AI 智能分析\n{ai_analysis}")

        return nodes

    def _generate_line_chart(
        self, summary: dict[str, Any], img_dir: Path, days: int
    ) -> None:
        """生成折线图：时间趋势"""
        daily_stats = summary["daily_stats"]
        if not daily_stats:
            return

        # 准备数据
        dates = sorted(daily_stats.keys())
        tokens = [daily_stats[d]["tokens"] for d in dates]
        prompt_tokens = [daily_stats[d]["prompt_tokens"] for d in dates]
        completion_tokens = [daily_stats[d]["completion_tokens"] for d in dates]

        # 创建图表
        fig, ax = plt.subplots(figsize=(12, 7))

        # 绘制折线
        ax.plot(
            dates, tokens, marker="o", linewidth=2, label="Total Token", color="#2196F3"
        )
        ax.plot(
            dates,
            prompt_tokens,
            marker="s",
            linewidth=2,
            label="Input Token",
            color="#4CAF50",
        )
        ax.plot(
            dates,
            completion_tokens,
            marker="^",
            linewidth=2,
            label="Output Token",
            color="#FF9800",
        )

        # 设置标题和标签
        ax.set_title(
            f"Token Usage Trend for Last {days} Days", fontsize=16, fontweight="bold"
        )
        ax.set_xlabel("Date", fontsize=12)
        ax.set_ylabel("Token Count", fontsize=12)
        ax.legend(loc="upper left", fontsize=10)
        ax.grid(True, alpha=0.3)

        # 旋转 x 轴标签
        plt.xticks(rotation=45, ha="right")

        # 调整布局
        plt.tight_layout()

        # 保存图表
        filepath = img_dir / "stats_line_chart.png"
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        plt.close(fig)

    def _generate_bar_chart(self, summary: dict[str, Any], img_dir: Path) -> None:
        """生成柱状图：模型对比"""
        models = summary["models"]
        if not models:
            return

        # 准备数据
        model_names = list(models.keys())
        tokens = [models[m]["tokens"] for m in model_names]
        prompt_tokens = [models[m]["prompt_tokens"] for m in model_names]
        completion_tokens = [models[m]["completion_tokens"] for m in model_names]

        # 创建图表
        fig, ax = plt.subplots(figsize=(14, 8))

        # 设置柱状图位置
        x = range(len(model_names))
        width = 0.25

        # 绘制柱状图
        bars1 = ax.bar(
            [i - width for i in x],
            tokens,
            width,
            label="Total Token",
            color="#2196F3",
            alpha=0.8,
        )
        bars2 = ax.bar(
            x,
            prompt_tokens,
            width,
            label="Input Token",
            color="#4CAF50",
            alpha=0.8,
        )
        bars3 = ax.bar(
            [i + width for i in x],
            completion_tokens,
            width,
            label="Output Token",
            color="#FF9800",
            alpha=0.8,
        )

        # 设置标题和标签
        ax.set_title("Token Usage Comparison by Model", fontsize=16, fontweight="bold")
        ax.set_xlabel("Model", fontsize=12)
        ax.set_ylabel("Token Count", fontsize=12)
        ax.set_xticks(x)
        ax.set_xticklabels(model_names, rotation=45, ha="right")
        ax.legend(loc="upper right", fontsize=10)
        ax.grid(True, alpha=0.3, axis="y")

        # 在柱子上添加数值标签
        for bars in [bars1, bars2, bars3]:
            for bar in bars:
                height = bar.get_height()
                if height > 0:
                    ax.text(
                        bar.get_x() + bar.get_width() / 2.0,
                        height,
                        f"{int(height):,}",
                        ha="center",
                        va="bottom",
                        fontsize=8,
                    )

        # 调整布局
        plt.tight_layout()

        # 保存图表
        filepath = img_dir / "stats_bar_chart.png"
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        plt.close(fig)

    def _generate_pie_chart(self, summary: dict[str, Any], img_dir: Path) -> None:
        """生成饼图：输入/输出比例"""
        prompt_tokens = summary["prompt_tokens"]
        completion_tokens = summary["completion_tokens"]

        if prompt_tokens == 0 and completion_tokens == 0:
            return

        # 创建图表
        fig, ax = plt.subplots(figsize=(12, 8))

        # 准备数据
        labels = ["Input Token", "Output Token"]
        sizes = [prompt_tokens, completion_tokens]
        colors = ["#4CAF50", "#FF9800"]
        explode = (0.05, 0.05)  # 突出显示

        # 绘制饼图
        wedges, *_ = ax.pie(
            sizes,
            explode=explode,
            labels=labels,
            colors=colors,
            autopct="%1.1f%%",
            startangle=90,
            textprops={"fontsize": 12},
        )

        # 设置标题
        ax.set_title("Input/Output Token Ratio", fontsize=16, fontweight="bold", pad=20)

        # 添加图例
        ax.legend(
            wedges,
            [f"{labels[i]}: {sizes[i]:,}" for i in range(len(labels))],
            loc="center left",
            bbox_to_anchor=(1, 0, 0.5, 1),
            fontsize=10,
        )

        # 调整布局
        plt.tight_layout()

        # 保存图表
        filepath = img_dir / "stats_pie_chart.png"
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        plt.close(fig)

    def _generate_stats_table(self, summary: dict[str, Any], img_dir: Path) -> None:
        """生成统计表格"""
        models = summary["models"]
        if not models:
            return

        # 准备数据
        model_names = list(models.keys())
        data = []
        for model in model_names:
            m = models[model]
            data.append(
                [
                    model,
                    m["calls"],
                    f"{m['tokens']:,}",
                    f"{m['prompt_tokens']:,}",
                    f"{m['completion_tokens']:,}",
                ]
            )

        # 创建图表
        fig, ax = plt.subplots(figsize=(14, 9))
        ax.axis("tight")
        ax.axis("off")

        # 创建表格
        table = ax.table(
            cellText=data,
            colLabels=["Model", "Calls", "Total Token", "Input Token", "Output Token"],
            cellLoc="center",
            loc="center",
        )

        # 设置表格样式
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1.2, 1.5)

        # 设置表头样式
        for i in range(5):
            table[(0, i)].set_facecolor("#2196F3")
            table[(0, i)].set_text_props(weight="bold", color="white")

        # 设置行样式
        for i in range(1, len(data) + 1):
            for j in range(5):
                if i % 2 == 0:
                    table[(i, j)].set_facecolor("#f0f0f0")

        # 设置标题
        ax.set_title(
            "Model Usage Statistics Details", fontsize=16, fontweight="bold", pad=20
        )

        # 调整布局
        plt.tight_layout()

        # 保存图表
        filepath = img_dir / "stats_table.png"
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        plt.close(fig)
