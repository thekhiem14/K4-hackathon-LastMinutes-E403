"""Slash commands: /mypoints and /report — AI rubric leaderboard."""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from db.database import Database, UserGradeStats
from scoring.points import breakdown_lines

logger = logging.getLogger(__name__)

EMBED_COLOR = 0xE39C6B
TOP_N = 15


class PointsCommands(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database) -> None:
        self.bot = bot
        self.db = db

    @app_commands.command(
        name="mypoints",
        description="Xem điểm AI rubric (tính mới / chất lượng / tương tác) của bạn",
    )
    async def mypoints(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=False)
        stats = await self.db.fetch_user_stats(str(interaction.user.id))

        if stats is None:
            await interaction.followup.send(
                f"{interaction.user.mention} chưa có bài nào được AI chấm "
                "(status=`graded`). Đợi bot chấm post mới, hoặc admin `/regrade` / `/syncnow`.",
            )
            return

        embed = discord.Embed(
            title="📊 Điểm AI rubric của bạn",
            description=(
                f"Cho {interaction.user.mention}\n"
                "_Tổng điểm cộng dồn từ các bài đã được AI chấm_\n"
                "Tính mới 40% · Chất lượng 40% · Tương tác 20% (có trần +1.5 / bài)"
            ),
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        for label, value in breakdown_lines(stats):
            embed.add_field(name=label, value=value, inline=False)
        embed.add_field(name="Hạng", value=f"#{stats.rank}" if stats.rank else "—", inline=True)
        embed.add_field(name="Tổng điểm", value=f"**{stats.total_points:.2f}**", inline=True)

        await interaction.followup.send(
            content=f"{interaction.user.mention} đây là điểm AI của bạn:",
            embed=embed,
        )

    @app_commands.command(
        name="report",
        description="[Admin] Bảng xếp hạng AI rubric + file CSV",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def report(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=False)
        board = await self.db.fetch_leaderboard()
        if not board:
            await interaction.followup.send(
                f"{interaction.user.mention} chưa có bản nháp AI nào (`grades`). "
                "Chấm bài bằng post mới hoặc `/regrade`.",
            )
            return

        embed = _leaderboard_embed(board)
        csv_file = _leaderboard_csv(board)
        await interaction.followup.send(
            content=f"{interaction.user.mention} báo cáo AI rubric — chia-sẻ:",
            embed=embed,
            file=csv_file,
        )

    @report.error
    async def report_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            msg = "❌ Bạn cần quyền **Administrator** để dùng `/report`."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        logger.exception("/report failed")
        msg = "Có lỗi khi tạo báo cáo."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


def _leaderboard_embed(board: list[UserGradeStats]) -> discord.Embed:
    lines = [
        f"**#{e.rank}** {e.display_name} — **{e.total_points:.2f}** "
        f"(mới {e.sum_novelty:.1f} · CL {e.sum_quality:.1f} · TT {e.sum_interaction:.1f} · {e.graded_posts} bài)"
        for e in board[:TOP_N]
    ]
    embed = discord.Embed(
        title="🏆 Bảng xếp hạng AI rubric — chia-sẻ",
        description="\n".join(lines),
        color=EMBED_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    footer = (
        f"Top {TOP_N}/{len(board)} theo tổng điểm cộng dồn — CSV đính kèm"
        if len(board) > TOP_N
        else f"{len(board)} thành viên — CSV đính kèm"
    )
    embed.set_footer(text=footer)
    return embed


def _leaderboard_csv(board: list[UserGradeStats]) -> discord.File:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "rank",
            "user_id",
            "display_name",
            "graded_posts",
            "sum_novelty",
            "sum_quality",
            "sum_interaction",
            "total_points",
            "needs_review_posts",
        ]
    )
    for e in board:
        writer.writerow(
            [
                e.rank,
                e.user_id,
                e.display_name,
                e.graded_posts,
                f"{e.sum_novelty:.2f}",
                f"{e.sum_quality:.2f}",
                f"{e.sum_interaction:.2f}",
                f"{e.total_points:.2f}",
                e.needs_review_posts,
            ]
        )
    data = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return discord.File(data, filename=f"chia-se-ai-rubric-report_{stamp}.csv")
