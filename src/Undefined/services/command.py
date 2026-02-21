import asyncio
import logging
import re
import time
from uuid import uuid4
from datetime import datetime
from typing import Any, Optional
from pathlib import Path

from Undefined.config import Config
from Undefined.faq import FAQStorage, extract_faq_title
from Undefined.onebot import (
    OneBotClient,
    get_message_content,
    get_message_sender_id,
    parse_message_time,
)
from Undefined.utils.sender import MessageSender
from Undefined.services.commands.context import CommandContext
from Undefined.services.commands.registry import CommandMeta, CommandRegistry
from Undefined.services.security import SecurityService
from Undefined.token_usage_storage import TokenUsageStorage

# 尝试导入 matplotlib
plt: Any
try:
    import matplotlib.pyplot as plt

    _MATPLOTLIB_AVAILABLE = True
except ImportError:
    plt = None
    _MATPLOTLIB_AVAILABLE = False

logger = logging.getLogger(__name__)


_STATS_DEFAULT_DAYS = 7
_STATS_MIN_DAYS = 1
_STATS_MAX_DAYS = 365
_STATS_MODEL_TOP_N = 8
_STATS_CALL_TYPE_TOP_N = 12
_STATS_DATA_SUMMARY_MAX_CHARS = 12000


class CommandDispatcher:
    """命令分发处理器，负责解析和执行斜杠命令"""

    def __init__(
        self,
        config: Config,
        sender: MessageSender,
        ai: Any,  # AIClient
        faq_storage: FAQStorage,
        onebot: OneBotClient,
        security: SecurityService,
        queue_manager: Any = None,
        rate_limiter: Any = None,
    ) -> None:
        """初始化命令分发器

        参数:
            config: 全局配置实例
            sender: 消息发送助手
            ai: AI 客户端(用于归纳和标题生成)
            faq_storage: FAQ 存储管理器
            onebot: OneBot HTTP API 客户端
            security: 安全审计与限流服务
            queue_manager: AI 请求队列管理器
            rate_limiter: 速率限制器
        """
        self.config = config
        self.sender = sender
        self.ai = ai
        self.faq_storage = faq_storage
        self.onebot = onebot
        self.security = security
        self.queue_manager = queue_manager
        self.rate_limiter = rate_limiter
        self._token_usage_storage = TokenUsageStorage()
        # 存储 stats 分析结果，用于队列回调
        self._stats_analysis_results: dict[str, str] = {}
        self._stats_analysis_events: dict[str, asyncio.Event] = {}

        commands_dir = Path(__file__).parent / "commands"
        self.command_registry = CommandRegistry(commands_dir)
        self.command_registry.load_commands()
        logger.info("[命令] 命令系统初始化完成: dir=%s", commands_dir)

    def parse_command(self, text: str) -> Optional[dict[str, Any]]:
        """解析斜杠命令字符串

        参数:
            text: 原始文本内容

        返回:
            包含命令名(name)和参数列表(args)的字典，解析失败则返回 None
        """
        clean_text = re.sub(r"\[@\s*\d+(?:\(.*?\))?\]", "", text).strip()
        match = re.match(r"/(\w+)\s*(.*)", clean_text)
        if not match:
            return None

        cmd_name = match.group(1).lower()
        args_str = match.group(2).strip()

        logger.debug(
            "[命令] 解析命令: text_len=%s cmd=%s args=%s",
            len(text),
            cmd_name,
            args_str,
        )
        return {
            "name": cmd_name,
            "args": args_str.split() if args_str else [],
        }

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

    async def _handle_stats(
        self, group_id: int, sender_id: int, args: list[str]
    ) -> None:
        """处理 /stats 命令，生成 token 使用统计图表并进行 AI 分析"""
        # 1. 基础环境与参数检查
        if not _MATPLOTLIB_AVAILABLE:
            await self.sender.send_group_message(
                group_id, "❌ 缺少必要的库，无法生成图表。请安装 matplotlib。"
            )
            return

        if args and args[0] == "--help":
            await self._handle_stats_help(group_id)
            return

        days = self._parse_time_range(args[0]) if args else 7

        try:
            # 2. 获取并验证数据
            summary = await self._token_usage_storage.get_summary(days=days)
            if summary["total_calls"] == 0:
                await self.sender.send_group_message(
                    group_id, f"📊 最近 {days} 天内无 Token 使用记录。"
                )
                return

            # 3. 生成图表文件
            from Undefined.utils.paths import RENDER_CACHE_DIR, ensure_dir

            img_dir = ensure_dir(RENDER_CACHE_DIR)
            await self._generate_line_chart(summary, img_dir, days)
            await self._generate_bar_chart(summary, img_dir)
            await self._generate_pie_chart(summary, img_dir)
            await self._generate_stats_table(summary, img_dir)

            # 4. 投递 AI 分析请求到队列
            ai_analysis = ""
            if self.queue_manager:
                # 构建数据摘要
                data_summary = self._build_data_summary(summary, days)

                # 创建事件等待分析结果
                request_id = uuid4().hex
                analysis_event = asyncio.Event()
                self._stats_analysis_events[request_id] = analysis_event

                # 投递到队列
                request_data = {
                    "type": "stats_analysis",
                    "group_id": group_id,
                    "request_id": request_id,
                    "sender_id": sender_id,
                    "data_summary": data_summary,
                    "summary": summary,
                    "days": days,
                }
                await self.queue_manager.add_group_mention_request(
                    request_data, model_name=self.config.chat_model.model_name
                )
                logger.info(f"[Stats] 已投递 AI 分析请求到队列，群: {group_id}")

                # 等待 AI 分析结果，8分钟超时
                try:
                    await asyncio.wait_for(analysis_event.wait(), timeout=480.0)
                    ai_analysis = self._stats_analysis_results.pop(request_id, "")
                    logger.info(f"[Stats] 已获取 AI 分析结果，长度: {len(ai_analysis)}")
                except asyncio.TimeoutError:
                    logger.warning(f"[Stats] AI 分析超时，群: {group_id}，仅发送图表")
                    ai_analysis = "AI 分析超时，已先发送图表与汇总数据。"
                finally:
                    self._stats_analysis_events.pop(request_id, None)
                    self._stats_analysis_results.pop(request_id, None)

            # 5. 构建并发送合并转发消息（包含 AI 分析）
            forward_messages = self._build_stats_forward_nodes(
                summary, img_dir, days, ai_analysis
            )
            await self.onebot.send_forward_msg(group_id, forward_messages)

            from Undefined.utils.cache import cleanup_cache_dir

            cleanup_cache_dir(RENDER_CACHE_DIR)

        except Exception as e:
            error_id = uuid4().hex[:8]
            logger.exception(
                "[Stats] 生成统计图表失败: error_id=%s err=%s", error_id, e
            )
            await self.sender.send_group_message(
                group_id,
                f"❌ 生成统计图表失败，请稍后重试（错误码: {error_id}）",
            )

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

    async def _handle_stats_help(self, group_id: int) -> None:
        """发送 stats 命令的帮助信息"""
        help_text = """📊 /stats 命令帮助

用法：
  /stats [时间范围]

时间范围格式：
  7d  - 最近 7 天（默认）
  1w  - 最近 1 周
  30d - 最近 30 天
  1m  - 最近 1 个月

示例：
  /stats        - 显示最近 7 天的统计
  /stats 30d    - 显示最近 30 天的统计
  /stats --help - 显示帮助信息"""
        await self.sender.send_group_message(group_id, help_text)

    def _build_stats_forward_nodes(
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
            if img_path.exists():
                add_node(f"[CQ:image,file={str(img_path.absolute())}]")

        # 添加文本摘要
        summary_text = f"""📈 摘要汇总:
• 总调用次数: {summary["total_calls"]}
• 总消耗 Tokens: {summary["total_tokens"]:,}
  └─ 输入: {summary["prompt_tokens"]:,}
  └─ 输出: {summary["completion_tokens"]:,}
• 平均耗时: {summary["avg_duration"]:.2f}s
• 涉及模型数: {len(summary["models"])}"""
        add_node(summary_text)

        # 添加 AI 分析结果（如果有）
        if ai_analysis:
            add_node(f"🤖 AI 智能分析\n{ai_analysis}")

        return nodes

    async def _generate_line_chart(
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

    async def _generate_bar_chart(self, summary: dict[str, Any], img_dir: Path) -> None:
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

    async def _generate_pie_chart(self, summary: dict[str, Any], img_dir: Path) -> None:
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

    async def _generate_stats_table(
        self, summary: dict[str, Any], img_dir: Path
    ) -> None:
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

    async def dispatch(
        self, group_id: int, sender_id: int, command: dict[str, Any]
    ) -> None:
        """分发并执行具体的命令

        参数:
            group_id: 消息来源群组
            sender_id: 发送者 QQ 号
            command: 解析出的命令数据结构
        """
        start_time = time.perf_counter()
        cmd_name = str(command["name"])
        cmd_args = command["args"]

        logger.info("[命令] 执行命令: /%s | 参数=%s", cmd_name, cmd_args)
        logger.debug(
            "[命令] 分发请求: group=%s sender=%s cmd=%s args_count=%s",
            group_id,
            sender_id,
            cmd_name,
            len(cmd_args),
        )

        meta = self.command_registry.resolve(cmd_name)
        if meta is None:
            logger.info("[命令] 未知命令: /%s", cmd_name)
            await self.sender.send_group_message(
                group_id,
                f"❌ 未知命令: {cmd_name}\n使用 /help 查看可用命令",
            )
            return

        logger.info(
            "[命令] 命令匹配成功: input=/%s resolved=/%s permission=%s rate_limit=%s",
            cmd_name,
            meta.name,
            meta.permission,
            meta.rate_limit,
        )

        allowed, role_name = self._check_command_permission(meta, sender_id)
        if not allowed:
            logger.warning(
                "[命令] 权限校验失败: cmd=/%s sender=%s required=%s",
                meta.name,
                sender_id,
                role_name,
            )
            await self._send_no_permission(group_id, sender_id, meta.name, role_name)
            return

        logger.debug(
            "[命令] 权限校验通过: cmd=/%s sender=%s",
            meta.name,
            sender_id,
        )

        if not await self._check_command_rate_limit(meta, group_id, sender_id):
            logger.warning(
                "[命令] 速率限制拦截: cmd=/%s group=%s sender=%s",
                meta.name,
                group_id,
                sender_id,
            )
            return

        logger.debug(
            "[命令] 速率限制通过: cmd=/%s group=%s sender=%s",
            meta.name,
            group_id,
            sender_id,
        )

        context = CommandContext(
            group_id=group_id,
            sender_id=sender_id,
            config=self.config,
            sender=self.sender,
            ai=self.ai,
            faq_storage=self.faq_storage,
            onebot=self.onebot,
            security=self.security,
            queue_manager=self.queue_manager,
            rate_limiter=self.rate_limiter,
            dispatcher=self,
            registry=self.command_registry,
        )

        try:
            await self.command_registry.execute(meta, cmd_args, context)
            duration = time.perf_counter() - start_time
            logger.info(
                "[命令] 分发完成: cmd=/%s duration=%.3fs",
                meta.name,
                duration,
            )
        except Exception as e:
            duration = time.perf_counter() - start_time
            error_id = uuid4().hex[:8]
            logger.exception(
                "[命令] 执行失败: cmd=/%s error_id=%s err=%s",
                meta.name,
                error_id,
                e,
            )
            logger.error(
                "[命令] 分发失败: cmd=/%s duration=%.3fs error_id=%s",
                meta.name,
                duration,
                error_id,
            )
            await self.sender.send_group_message(
                group_id,
                f"❌ 命令执行失败，请稍后重试（错误码: {error_id}）",
            )

    def _check_command_permission(
        self,
        command_meta: CommandMeta,
        sender_id: int,
    ) -> tuple[bool, str]:
        permission = command_meta.permission
        if permission == "superadmin":
            return self.config.is_superadmin(sender_id), "超级管理员"
        if permission == "admin":
            return self.config.is_admin(sender_id), "管理员"
        return True, ""

    async def _check_command_rate_limit(
        self,
        command_meta: CommandMeta,
        group_id: int,
        sender_id: int,
    ) -> bool:
        rate_limit = command_meta.rate_limit
        if rate_limit == "none":
            logger.debug(
                "[命令] 命令无需限流: cmd=/%s",
                command_meta.name,
            )
            return True

        if rate_limit == "stats":
            if self.rate_limiter is None:
                logger.warning(
                    "[命令] stats 限流器缺失，跳过限流: cmd=/%s",
                    command_meta.name,
                )
                return True
            allowed, remaining = self.rate_limiter.check_stats(sender_id)
            if not allowed:
                minutes = remaining // 60
                seconds = remaining % 60
                time_str = f"{minutes}分{seconds}秒" if minutes > 0 else f"{seconds}秒"
                await self.sender.send_group_message(
                    group_id,
                    f"⏳ /stats 命令太频繁，请 {time_str}后再试",
                )
                return False
            self.rate_limiter.record_stats(sender_id)
            logger.debug(
                "[命令] stats 限流记录成功: cmd=/%s sender=%s",
                command_meta.name,
                sender_id,
            )
            return True

        allowed, remaining = self.security.check_rate_limit(sender_id)
        if not allowed:
            await self.sender.send_group_message(
                group_id,
                f"⏳ 操作太频繁，请 {remaining} 秒后再试",
            )
            return False
        self.security.record_rate_limit(sender_id)
        logger.debug(
            "[命令] 默认限流记录成功: cmd=/%s sender=%s",
            command_meta.name,
            sender_id,
        )
        return True

    async def _send_no_permission(
        self, group_id: int, sender_id: int, cmd_name: str, required_role: str
    ) -> None:
        logger.warning("[命令] 权限不足: sender=%s cmd=/%s", sender_id, cmd_name)
        await self.sender.send_group_message(
            group_id, f"⚠️ 权限不足：只有{required_role}可以使用此命令"
        )

    async def _handle_bugfix(
        self, group_id: int, admin_id: int, args: list[str]
    ) -> None:
        """处理 /bugfix 命令，通过分析聊天记录自动生成 FAQ 归档"""
        # 1. 参数解析
        parsed = self._parse_bugfix_args(args)
        if isinstance(parsed, str):
            await self.sender.send_group_message(group_id, parsed)
            return

        target_qqs, start_date, end_date, start_str, end_str = parsed

        await self.sender.send_group_message(
            group_id, "🔍 正在获取对话记录进行回溯分析..."
        )

        try:
            # 2. 获取并处理消息
            messages = await self._fetch_messages(
                group_id, target_qqs, start_date, end_date
            )
            if not messages:
                await self.sender.send_group_message(
                    group_id, "❌ 未找到符合条件的对话记录。"
                )
                return

            processed_text = await self._process_messages(messages)

            # 3. 生成摘要总结
            summary = await self._obtain_bugfix_summary(group_id, processed_text)

            # 4. 生成标题并入库
            title = extract_faq_title(summary)
            if not title or title == "未命名问题":
                title = await self.ai.generate_title(summary)

            faq = await self.faq_storage.create(
                group_id=group_id,
                target_qq=target_qqs[0],
                start_time=start_str,
                end_time=end_str,
                title=title,
                content=summary,
            )

            result_msg = f"✅ Bug 修复分析完成！\n\n📌 FAQ ID: {faq.id}\n📋 标题: {title}\n\n{summary}"
            await self.sender.send_group_message(group_id, result_msg)

        except Exception as e:
            error_id = uuid4().hex[:8]
            logger.exception("Bugfix 失败: error_id=%s err=%s", error_id, e)
            await self.sender.send_group_message(
                group_id,
                f"❌ Bug 修复分析失败，请稍后重试（错误码: {error_id}）",
            )

    def _parse_bugfix_args(
        self, args: list[str]
    ) -> tuple[list[int], datetime, datetime, str, str] | str:
        """解析 bugfix 命令的参数"""
        if len(args) < 3:
            return (
                "❌ 用法: /bugfix <QQ号1> [QQ号2] ... <开始时间> <结束时间>\n"
                "时间格式: YYYY/MM/DD/HH:MM，结束时间可用 now\n"
                "示例: /bugfix 123456 2024/12/01/09:00 now"
            )

        try:
            target_qqs = [int(arg) for arg in args[:-2]]
            start_str, end_str_raw = args[-2], args[-1]
            start_date = datetime.strptime(start_str, "%Y/%m/%d/%H:%M")

            if end_str_raw.lower() == "now":
                end_date, end_str = datetime.now(), "now"
            else:
                end_date, end_str = (
                    datetime.strptime(end_str_raw, "%Y/%m/%d/%H:%M"),
                    end_str_raw,
                )

            return target_qqs, start_date, end_date, start_str, end_str
        except ValueError:
            return "❌ 参数格式错误：QQ号应为数字，时间格式应为 YYYY/MM/DD/HH:MM。"

    async def _obtain_bugfix_summary(self, group_id: int, processed_text: str) -> str:
        """利用 AI 生成聊天记录的 Bug 分析摘要"""
        total_tokens = self.ai.count_tokens(processed_text)
        max_tokens = self.config.chat_model.max_tokens

        if total_tokens <= max_tokens:
            return str(await self.ai.summarize_chat(processed_text))

        await self.sender.send_group_message(
            group_id, f"📊 消息较长（{total_tokens} tokens），正在分段处理..."
        )
        chunks = self.ai.split_messages_by_tokens(processed_text, max_tokens)
        summaries = [await self.ai.summarize_chat(chunk) for chunk in chunks]
        return str(await self.ai.merge_summaries(summaries))

    async def _fetch_messages(
        self,
        group_id: int,
        target_qqs: list[int],
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict[str, Any]]:
        batch = await self.onebot.get_group_msg_history(group_id, count=2500)
        if not batch:
            return []
        target_qqs_set = set(target_qqs)
        results = []
        for msg in batch:
            msg_time = parse_message_time(msg)
            if (
                start_date <= msg_time <= end_date
                and get_message_sender_id(msg) in target_qqs_set
            ):
                results.append(msg)
        return sorted(results, key=lambda m: m.get("time", 0))

    async def _process_messages(self, messages: list[dict[str, Any]]) -> str:
        lines = []
        for msg in messages:
            sender_id = get_message_sender_id(msg)
            msg_time = parse_message_time(msg).strftime("%Y-%m-%d %H:%M:%S")
            content = get_message_content(msg)
            text_parts = []
            for segment in content:
                seg_type, seg_data = segment.get("type", ""), segment.get("data", {})
                if seg_type == "text":
                    text_parts.append(seg_data.get("text", ""))
                elif seg_type == "image":
                    file = seg_data.get("file", "") or seg_data.get("url", "")
                    if file:
                        try:
                            url = await self.onebot.get_image(file)
                            if url:
                                res = await self.ai.analyze_multimodal(url, "image")
                                text_parts.append(
                                    f"[pic]<desc>{res.get('description', '')}</desc><text>{res.get('ocr_text', '')}</text>[/pic]"
                                )
                        except Exception:
                            text_parts.append("[pic]<desc>图片处理失败</desc>[/pic]")
                elif seg_type == "at":
                    text_parts.append(f"@{seg_data.get('qq', '')}")
            if text_parts:
                lines.append(f"[{msg_time}] {sender_id}: {''.join(text_parts)}")
        return "\n".join(lines)
