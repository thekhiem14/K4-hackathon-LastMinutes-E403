"""Admin slash commands: /syncnow, /regrade."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from cogs.coach_delivery import grade_embed
from pipeline.run import run_grading_pipeline
from sync.forum_sync import thread_to_normalized

logger = logging.getLogger(__name__)


class CoachCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="syncnow",
        description="[Admin] Đồng bộ kho bài chia-sẻ + embeddings",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def syncnow(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        result = await self.bot.run_forum_sync(reason=f"manual:{interaction.user.id}")  # type: ignore[attr-defined]
        if result is None:
            await interaction.followup.send("Sync thất bại hoặc đang chạy.", ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Sync xong: **{result}** posts vào posts_history.",
            ephemeral=True,
        )

    @app_commands.command(
        name="regrade",
        description="[Admin] Chấm lại một forum post (thread ID)",
    )
    @app_commands.describe(thread_id="ID của thread/post trong kênh chia-sẻ")
    @app_commands.checks.has_permissions(administrator=True)
    async def regrade(self, interaction: discord.Interaction, thread_id: str) -> None:
        await interaction.response.defer(ephemeral=True)
        if self.bot.gemini is None:  # type: ignore[attr-defined]
            await interaction.followup.send(
                "OPENROUTER_API_KEY chưa cấu hình — không chấm được.",
                ephemeral=True,
            )
            return
        try:
            tid = int(thread_id.strip())
        except ValueError:
            await interaction.followup.send("thread_id không hợp lệ.", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("Chỉ dùng trong server.", ephemeral=True)
            return

        try:
            channel = await guild.fetch_channel(tid)
        except discord.HTTPException as exc:
            await interaction.followup.send(f"Không tìm thấy thread: {exc}", ephemeral=True)
            return

        if not isinstance(channel, discord.Thread):
            await interaction.followup.send("ID phải là forum thread.", ephemeral=True)
            return

        forum_id = self.bot.settings.forum_channel_id  # type: ignore[attr-defined]
        if channel.parent_id != forum_id:
            await interaction.followup.send(
                "Thread không thuộc kênh chia-sẻ đã cấu hình.",
                ephemeral=True,
            )
            return

        normalized, has_attach, attach_only = await thread_to_normalized(channel, forum_id)
        grade = await run_grading_pipeline(
            db=self.bot.db,  # type: ignore[attr-defined]
            gemini=self.bot.gemini,  # type: ignore[attr-defined]
            post=normalized,
            has_attachments=has_attach,
            attachment_only=attach_only,
        )
        await interaction.followup.send(
            content="Đã chấm và lưu vào DB. User xem bằng `/mypoints`.",
            embed=grade_embed(normalized, grade),
            ephemeral=True,
        )

    @syncnow.error
    @regrade.error
    async def admin_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            msg = "❌ Cần quyền Administrator."
        else:
            logger.exception("admin command failed")
            msg = "Lỗi lệnh admin."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CoachCommands(bot))
