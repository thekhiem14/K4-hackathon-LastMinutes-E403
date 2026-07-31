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

logger = logging.getLogger(__name__)

EMBED_COLOR = 0x0F766E
PODIUM_COLOR = 0xCA8A04
TOP_N = 15
_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


class PointsCommands(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database) -> None:
        self.bot = bot
        self.db = db

    @app_commands.command(
        name="mypoints",
        description="Xem điểm AI rubric (tính mới / chất lượng / tương tác) của bạn",
    )
    async def mypoints(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        stats = await self.db.fetch_user_stats(str(interaction.user.id))

        if stats is None:
            await interaction.followup.send(
                f"{interaction.user.mention} chưa có bài nào được AI chấm "
                "(status=`graded`). Đợi bot chấm post mới, hoặc admin `/regrade` / `/syncnow`.",
                ephemeral=True,
            )
            return

        embed = _mypoints_embed(interaction.user, stats)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="report",
        description="[Admin] Bảng xếp hạng AI rubric + file CSV",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def report(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        board = await self.db.fetch_leaderboard()
        if not board:
            await interaction.followup.send(
                "Chưa có bài nào được AI chấm (`grades`). "
                "Đăng bài mới trên chia-sẻ hoặc dùng `/regrade`.",
                ephemeral=True,
            )
            return

        if interaction.guild is not None:
            await _apply_display_names(board, interaction.guild)
        embeds = _report_embeds(board, guild=interaction.guild)
        csv_file = _leaderboard_csv(board)
        await interaction.followup.send(
            embeds=embeds,
            file=csv_file,
            ephemeral=True,
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


async def _apply_display_names(
    board: list[UserGradeStats],
    guild: discord.Guild,
) -> None:
    """Replace stored names with each member's current server display name."""
    for entry in board:
        try:
            uid = int(entry.user_id)
        except ValueError:
            continue
        member = guild.get_member(uid)
        if member is None:
            try:
                member = await guild.fetch_member(uid)
            except discord.HTTPException:
                member = None
        if member is not None:
            entry.display_name = member.display_name


def _mypoints_embed(user: discord.abc.User, stats: UserGradeStats) -> discord.Embed:
    rank = f"#{stats.rank}" if stats.rank else "—"
    embed = discord.Embed(
        title="Điểm AI rubric của bạn",
        description=(
            f"{user.mention}\n"
            "Cộng dồn từ các bài đã chấm · "
            "mới **40%** · chất lượng **40%** · tương tác **20%**"
        ),
        color=EMBED_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(
        name=getattr(user, "display_name", user.name),
        icon_url=user.display_avatar.url,
    )
    embed.add_field(name="Hạng", value=f"**{rank}**", inline=True)
    embed.add_field(name="Tổng điểm", value=f"**{stats.total_points:.2f}**", inline=True)
    embed.add_field(name="Bài đã chấm", value=f"**{stats.graded_posts}**", inline=True)
    embed.add_field(name="Tính mới", value=f"{stats.sum_novelty:.1f}", inline=True)
    embed.add_field(name="Chất lượng", value=f"{stats.sum_quality:.1f}", inline=True)
    embed.add_field(name="Tương tác", value=f"{stats.sum_interaction:.1f}", inline=True)
    if stats.needs_review_posts:
        embed.add_field(
            name="Bài bị flag",
            value=str(stats.needs_review_posts),
            inline=True,
        )
    embed.set_footer(text="Lab05 · chia-sẻ")
    return embed


def _report_embeds(
    board: list[UserGradeStats],
    *,
    guild: discord.Guild | None,
) -> list[discord.Embed]:
    total_posts = sum(e.graded_posts for e in board)
    top = board[0]

    lines: list[str] = []
    for e in board[:TOP_N]:
        rank_badge = _MEDALS.get(e.rank or 0, f"`#{e.rank}`")
        lines.append(
            f"{rank_badge} **{e.display_name}** — **{e.total_points:.2f}** pts\n"
            f"-# {e.graded_posts} bài · mới {e.sum_novelty:.1f} · "
            f"chất lượng {e.sum_quality:.1f} · tương tác {e.sum_interaction:.1f} · "
            f"ID {e.user_id}"
        )
    if len(board) > TOP_N:
        lines.append(f"-# … và {len(board) - TOP_N} thành viên nữa (xem CSV)")

    embed = discord.Embed(
        title="🏆 Báo cáo AI rubric — chia-sẻ",
        description=(
            f"**{len(board)}** thành viên · **{total_posts}** bài đã chấm · "
            f"dẫn đầu **{top.display_name}**\n\n"
            + "\n".join(lines)
        ),
        color=PODIUM_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    if guild is not None:
        embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
    embed.set_footer(
        text=(
            f"Top {min(TOP_N, len(board))}/{len(board)} · "
            "mới 40% · CL 40% · TT 20% · CSV đầy đủ đính kèm"
        )
    )
    return [embed]


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
