import logging
import re
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
from Undefined.services.security import SecurityService
from Undefined.token_usage_storage import TokenUsageStorage

# 尝试导入 matplotlib
try:
    import matplotlib.pyplot as plt

    _MATPLOTLIB_AVAILABLE = True
except ImportError:
    _MATPLOTLIB_AVAILABLE = False

logger = logging.getLogger(__name__)

with open("res/prepared_messages/help_message.txt", "r", encoding="utf-8") as f:
    HELP_MESSAGE = f.read()


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
    ) -> None:
        self.config = config
        self.sender = sender
        self.ai = ai
        self.faq_storage = faq_storage
        self.onebot = onebot
        self.security = security
        self._token_usage_storage = TokenUsageStorage()

    def parse_command(self, text: str) -> Optional[dict[str, Any]]:
        """解析命令"""
        clean_text = re.sub(r"\[@\s*\d+\]", "", text).strip()
        match = re.match(r"/(\w+)\s*(.*)", clean_text)
        if not match:
            return None

        cmd_name = match.group(1).lower()
        args_str = match.group(2).strip()

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
            return 7  # 默认 7 天

        time_str = time_str.lower().strip()

        # 解析快捷格式
        if time_str.endswith("d"):
            try:
                return int(time_str[:-1])
            except ValueError:
                return 7
        elif time_str.endswith("w"):
            try:
                return int(time_str[:-1]) * 7
            except ValueError:
                return 7
        elif time_str.endswith("m"):
            try:
                return int(time_str[:-1]) * 30
            except ValueError:
                return 7

        # 尝试直接解析为数字（默认为天）
        try:
            return int(time_str)
        except ValueError:
            return 7

    async def _handle_stats(self, group_id: int, args: list[str]) -> None:
        """处理 /stats 命令，生成 token 使用统计图表

        参数:
            group_id: 群组 ID
            args: 命令参数（时间范围，如 "7d", "1w", "30d"）
        """
        # 检查 matplotlib 是否可用
        if not _MATPLOTLIB_AVAILABLE:
            await self.sender.send_group_message(
                group_id, "❌ 缺少必要的库，无法生成图表。请安装 matplotlib 和 pandas。"
            )
            return

        # 解析时间范围
        days = 7
        if args and args[0] != "--help":
            days = self._parse_time_range(args[0])

        # 显示帮助信息
        if args and args[0] == "--help":
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
  /stats --help - 显示帮助信息

生成的图表包括：
  • 折线图：token 使用量随时间的变化趋势
  • 柱状图：不同模型的 token 使用量对比
  • 饼图：prompt 和 completion token 的比例
  • 统计表格：调用次数、平均耗时等统计信息"""
            await self.sender.send_group_message(group_id, help_text)
            return

        try:
            # 获取统计数据
            summary = await self._token_usage_storage.get_summary(days=days)

            if summary["total_calls"] == 0:
                await self.sender.send_group_message(
                    group_id, f"📊 No token usage records in the last {days} days."
                )
                return

            # 生成图表
            img_dir = Path.cwd() / "img"
            img_dir.mkdir(exist_ok=True)

            # 1. 折线图：时间趋势
            await self._generate_line_chart(summary, img_dir, days)

            # 2. 柱状图：模型对比
            await self._generate_bar_chart(summary, img_dir)

            # 3. 饼图：输入/输出比例
            await self._generate_pie_chart(summary, img_dir)

            # 4. 统计表格
            await self._generate_stats_table(summary, img_dir)

            # 构造合并转发消息
            forward_messages = []

            # 添加标题消息
            title_message = f"📊 Token Usage Statistics for Last {days} Days:"
            forward_messages.append(
                {
                    "type": "node",
                    "data": {
                        "name": "Bot",
                        "uin": str(self.config.bot_qq),
                        "content": title_message,
                    },
                }
            )

            # 添加折线图
            line_chart_path = img_dir / "stats_line_chart.png"
            if line_chart_path.exists():
                forward_messages.append(
                    {
                        "type": "node",
                        "data": {
                            "name": "Bot",
                            "uin": str(self.config.bot_qq),
                            "content": f"[CQ:image,file={str(line_chart_path.absolute())}]",
                        },
                    }
                )

            # 添加柱状图
            bar_chart_path = img_dir / "stats_bar_chart.png"
            if bar_chart_path.exists():
                forward_messages.append(
                    {
                        "type": "node",
                        "data": {
                            "name": "Bot",
                            "uin": str(self.config.bot_qq),
                            "content": f"[CQ:image,file={str(bar_chart_path.absolute())}]",
                        },
                    }
                )

            # 添加饼图
            pie_chart_path = img_dir / "stats_pie_chart.png"
            if pie_chart_path.exists():
                forward_messages.append(
                    {
                        "type": "node",
                        "data": {
                            "name": "Bot",
                            "uin": str(self.config.bot_qq),
                            "content": f"[CQ:image,file={str(pie_chart_path.absolute())}]",
                        },
                    }
                )

            # 添加统计表格
            stats_table_path = img_dir / "stats_table.png"
            if stats_table_path.exists():
                forward_messages.append(
                    {
                        "type": "node",
                        "data": {
                            "name": "Bot",
                            "uin": str(self.config.bot_qq),
                            "content": f"[CQ:image,file={str(stats_table_path.absolute())}]",
                        },
                    }
                )

            # 添加文本摘要
            summary_text = f"""📈 Summary:
• Total Calls: {summary["total_calls"]}
• Total Tokens: {summary["total_tokens"]:,}
  └─ Input: {summary["prompt_tokens"]:,}
  └─ Output: {summary["completion_tokens"]:,}
• Avg Duration: {summary["avg_duration"]:.2f}s
• Model Count: {len(summary["models"])}"""
            forward_messages.append(
                {
                    "type": "node",
                    "data": {
                        "name": "Bot",
                        "uin": str(self.config.bot_qq),
                        "content": summary_text,
                    },
                }
            )

            # 发送合并转发消息
            await self.onebot.send_forward_msg(group_id, forward_messages)

        except Exception as e:
            logger.exception(f"[Stats] 生成统计图表失败: {e}")
            await self.sender.send_group_message(group_id, f"❌ 生成统计图表失败: {e}")

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
        """分发并执行命令"""
        cmd_name = command["name"]
        cmd_args = command["args"]

        logger.info(f"[Command] 执行命令: /{cmd_name} | 参数: {cmd_args}")

        try:
            # 公开命令
            if cmd_name == "help":
                await self._handle_help(group_id)
            elif cmd_name == "stats":
                await self._check_rate_limit_and_handle(
                    group_id, sender_id, self._handle_stats, group_id, cmd_args
                )
            elif cmd_name == "lsfaq":
                await self._check_rate_limit_and_handle(
                    group_id, sender_id, self._handle_lsfaq, group_id
                )
            elif cmd_name == "viewfaq":
                await self._check_rate_limit_and_handle(
                    group_id, sender_id, self._handle_viewfaq, group_id, cmd_args
                )
            elif cmd_name == "searchfaq":
                await self._check_rate_limit_and_handle(
                    group_id, sender_id, self._handle_searchfaq, group_id, cmd_args
                )
            elif cmd_name == "lsadmin":
                await self._handle_lsadmin(group_id)

            # 管理员命令
            elif cmd_name == "delfaq":
                if not self.config.is_admin(sender_id):
                    await self._send_no_permission(
                        group_id, sender_id, cmd_name, "管理员"
                    )
                    return
                await self._check_rate_limit_and_handle(
                    group_id, sender_id, self._handle_delfaq, group_id, cmd_args
                )
            elif cmd_name == "bugfix":
                if not self.config.is_admin(sender_id):
                    await self._send_no_permission(
                        group_id, sender_id, cmd_name, "管理员"
                    )
                    return
                await self._check_rate_limit_and_handle(
                    group_id,
                    sender_id,
                    self._handle_bugfix,
                    group_id,
                    sender_id,
                    cmd_args,
                )

            # 超级管理员命令
            elif cmd_name == "addadmin":
                if not self.config.is_superadmin(sender_id):
                    await self._send_no_permission(
                        group_id, sender_id, cmd_name, "超级管理员"
                    )
                    return
                await self._handle_addadmin(group_id, cmd_args)
            elif cmd_name == "rmadmin":
                if not self.config.is_superadmin(sender_id):
                    await self._send_no_permission(
                        group_id, sender_id, cmd_name, "超级管理员"
                    )
                    return
                await self._handle_rmadmin(group_id, cmd_args)

            else:
                logger.info(f"[Command] 未知命令: /{cmd_name}")
                await self.sender.send_group_message(
                    group_id, f"❌ 未知命令: {cmd_name}\n使用 /help 查看可用命令"
                )
        except Exception as e:
            logger.exception(f"[Command] 执行 /{cmd_name} 失败: {e}")
            await self.sender.send_group_message(group_id, f"❌ 命令执行失败: {e}")

    async def _check_rate_limit_and_handle(
        self, group_id: int, user_id: int, handler: Any, *args: Any
    ) -> None:
        """检查速率限制并执行"""
        allowed, remaining = self.security.check_rate_limit(user_id)
        if not allowed:
            await self.sender.send_group_message(
                group_id, f"⏳ 操作太频繁，请 {remaining} 秒后再试"
            )
            return
        self.security.record_rate_limit(user_id)
        await handler(*args)

    async def _send_no_permission(
        self, group_id: int, sender_id: int, cmd_name: str, required_role: str
    ) -> None:
        logger.warning(f"[Command] 权限不足: {sender_id} 尝试执行 /{cmd_name}")
        await self.sender.send_group_message(
            group_id, f"⚠️ 权限不足：只有{required_role}可以使用此命令"
        )

    async def _handle_help(self, group_id: int) -> None:
        await self.sender.send_group_message(group_id, HELP_MESSAGE)

    async def _handle_lsfaq(self, group_id: int) -> None:
        faqs = await self.faq_storage.list_all(group_id)
        if not faqs:
            await self.sender.send_group_message(group_id, "📭 当前群组没有保存的 FAQ")
            return
        lines = ["📋 FAQ 列表：", ""]
        for faq in faqs[:20]:
            lines.append(f"📌 [{faq.id}] {faq.title}")
            lines.append(f"   创建时间: {faq.created_at[:10]}")
            lines.append("")
        if len(faqs) > 20:
            lines.append(f"... 还有 {len(faqs) - 20} 条")
        await self.sender.send_group_message(group_id, "\n".join(lines))

    async def _handle_viewfaq(self, group_id: int, args: list[str]) -> None:
        if not args:
            await self.sender.send_group_message(
                group_id, "❌ 用法: /viewfaq <ID>\n示例: /viewfaq 20241205-001"
            )
            return
        faq_id = args[0]
        faq = await self.faq_storage.get(group_id, faq_id)
        if not faq:
            await self.sender.send_group_message(group_id, f"❌ FAQ 不存在: {faq_id}")
            return
        message = f"📖 FAQ: {faq.title}\n\n🆔 ID: {faq.id}\n👤 分析对象: {faq.target_qq}\n📅 时间范围: {faq.start_time} ~ {faq.end_time}\n🕐 创建时间: {faq.created_at}\n\n{faq.content}"
        await self.sender.send_group_message(group_id, message)

    async def _handle_searchfaq(self, group_id: int, args: list[str]) -> None:
        if not args:
            await self.sender.send_group_message(
                group_id, "❌ 用法: /searchfaq <关键词>\n示例: /searchfaq 登录"
            )
            return
        keyword = " ".join(args)
        results = await self.faq_storage.search(group_id, keyword)
        if not results:
            await self.sender.send_group_message(
                group_id, f'🔍 未找到包含 "{keyword}" 的 FAQ'
            )
            return
        lines = [f'🔍 搜索 "{keyword}" 找到 {len(results)} 条结果：', ""]
        for faq in results[:10]:
            lines.append(f"📌 [{faq.id}] {faq.title}")
            lines.append("")
        if len(results) > 10:
            lines.append(f"... 还有 {len(results) - 10} 条")
        lines.append("\n使用 /viewfaq <ID> 查看详情")
        await self.sender.send_group_message(group_id, "\n".join(lines))

    async def _handle_delfaq(self, group_id: int, args: list[str]) -> None:
        if not args:
            await self.sender.send_group_message(
                group_id, "❌ 用法: /delfaq <ID>\n示例: /delfaq 20241205-001"
            )
            return
        faq_id = args[0]
        faq = await self.faq_storage.get(group_id, faq_id)
        if not faq:
            await self.sender.send_group_message(group_id, f"❌ FAQ 不存在: {faq_id}")
            return
        if await self.faq_storage.delete(group_id, faq_id):
            await self.sender.send_group_message(
                group_id, f"✅ 已删除 FAQ: [{faq_id}] {faq.title}"
            )
        else:
            await self.sender.send_group_message(group_id, f"❌ 删除失败: {faq_id}")

    async def _handle_lsadmin(self, group_id: int) -> None:
        lines = [f"👑 超级管理员: {self.config.superadmin_qq}"]
        admins = [qq for qq in self.config.admin_qqs if qq != self.config.superadmin_qq]
        if admins:
            admin_list = "\n".join([f"- {qq}" for qq in admins])
            lines.append(f"\n📋 管理员列表：\n{admin_list}")
        else:
            lines.append("\n📋 暂无其他管理员")
        await self.sender.send_group_message(group_id, "\n".join(lines))

    async def _handle_addadmin(self, group_id: int, args: list[str]) -> None:
        if not args:
            await self.sender.send_group_message(
                group_id, "❌ 用法: /addadmin <QQ号>\n示例: /addadmin 123456789"
            )
            return
        try:
            new_admin_qq = int(args[0])
        except ValueError:
            await self.sender.send_group_message(
                group_id, "❌ QQ 号格式错误，必须为数字"
            )
            return
        if self.config.is_admin(new_admin_qq):
            await self.sender.send_group_message(
                group_id, f"⚠️ {new_admin_qq} 已经是管理员了"
            )
            return
        try:
            self.config.add_admin(new_admin_qq)
            await self.sender.send_group_message(
                group_id, f"✅ 已添加管理员: {new_admin_qq}"
            )
        except Exception as e:
            logger.exception(f"添加管理员失败: {e}")
            await self.sender.send_group_message(group_id, f"❌ 添加管理员失败: {e}")

    async def _handle_rmadmin(self, group_id: int, args: list[str]) -> None:
        if not args:
            await self.sender.send_group_message(
                group_id, "❌ 用法: /rmadmin <QQ号>\n示例: /rmadmin 123456789"
            )
            return
        try:
            target_qq = int(args[0])
        except ValueError:
            await self.sender.send_group_message(
                group_id, "❌ QQ 号格式错误，必须为数字"
            )
            return
        if self.config.is_superadmin(target_qq):
            await self.sender.send_group_message(group_id, "❌ 无法移除超级管理员")
            return
        if not self.config.is_admin(target_qq):
            await self.sender.send_group_message(group_id, f"⚠️ {target_qq} 不是管理员")
            return
        try:
            self.config.remove_admin(target_qq)
            await self.sender.send_group_message(
                group_id, f"✅ 已移除管理员: {target_qq}"
            )
        except Exception as e:
            logger.exception(f"移除管理员失败: {e}")
            await self.sender.send_group_message(group_id, f"❌ 移除管理员失败: {e}")

    async def _handle_bugfix(
        self, group_id: int, admin_id: int, args: list[str]
    ) -> None:
        if len(args) < 3:
            await self.sender.send_group_message(
                group_id,
                "❌ 用法: /bugfix <QQ号1> [QQ号2] ... <开始时间> <结束时间>\n"
                "时间格式: YYYY/MM/DD/HH:MM，结束时间可用 now\n"
                "示例: /bugfix 123456 2024/12/01/09:00 now",
            )
            return

        target_qqs: list[int] = []
        time_args = args[-2:]
        qq_args = args[:-2]
        try:
            for arg in qq_args:
                target_qqs.append(int(arg))
        except ValueError:
            await self.sender.send_group_message(
                group_id, "❌ QQ 号格式错误，必须为数字"
            )
            return

        try:
            start_date = datetime.strptime(time_args[0], "%Y/%m/%d/%H:%M")
            if time_args[1].lower() == "now":
                end_date = datetime.now()
                end_date_str = "now"
            else:
                end_date = datetime.strptime(time_args[1], "%Y/%m/%d/%H:%M")
                end_date_str = time_args[1]
        except ValueError:
            await self.sender.send_group_message(
                group_id, "❌ 时间格式错误，请使用 YYYY/MM/DD/HH:MM 格式"
            )
            return

        await self.sender.send_group_message(group_id, "🔍 正在获取对话记录...")

        try:
            messages = await self._fetch_messages(
                group_id, target_qqs, start_date, end_date
            )
            if not messages:
                await self.sender.send_group_message(
                    group_id, "❌ 未找到符合条件的对话记录"
                )
                return

            processed_text = await self._process_messages(messages)
            total_tokens = self.ai.count_tokens(processed_text)
            max_tokens = self.config.chat_model.max_tokens

            if total_tokens <= max_tokens:
                summary = await self.ai.summarize_chat(processed_text)
            else:
                await self.sender.send_group_message(
                    group_id, f"📊 消息较长（{total_tokens} tokens），正在分段处理..."
                )
                chunks = self.ai.split_messages_by_tokens(processed_text, max_tokens)
                summaries = [await self.ai.summarize_chat(chunk) for chunk in chunks]
                summary = await self.ai.merge_summaries(summaries)

            title = extract_faq_title(summary)
            if not title or title == "未命名问题":
                title = await self.ai.generate_title(summary)

            faq = await self.faq_storage.create(
                group_id=group_id,
                target_qq=target_qqs[0],
                start_time=time_args[0],
                end_time=end_date_str,
                title=title,
                content=summary,
            )
            await self.sender.send_group_message(
                group_id,
                f"✅ Bug 修复分析完成！\n\n📌 FAQ ID: {faq.id}\n📋 标题: {title}\n\n{summary}",
            )
        except Exception as e:
            logger.exception(f"Bugfix 失败: {e}")
            await self.sender.send_group_message(group_id, f"❌ Bug 修复分析失败: {e}")

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
        results = []
        for msg in batch:
            msg_time = parse_message_time(msg)
            if (
                start_date <= msg_time <= end_date
                and get_message_sender_id(msg) in target_qqs
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
