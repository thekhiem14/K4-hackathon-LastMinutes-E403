"""Moderate new chia-sẻ forum posts: allow or delete (+ DM reason)."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from pipeline.censor import censor_post

logger = logging.getLogger(__name__)

_ALLOW_EMOJI = "✅"
_PROCESSED: set[int] = set()
_PROCESSED_MAX = 500


class ForumCensor(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread) -> None:
        await self._maybe_censor(thread)

    async def _maybe_censor(self, thread: discord.Thread) -> None:
        forum_id = self.bot.settings.forum_channel_id  # type: ignore[attr-defined]
        if thread.parent_id != forum_id:
            return
        if thread.id in _PROCESSED:
            return
        if thread.owner_id and self.bot.user and thread.owner_id == self.bot.user.id:
            return

        # Starter message can lag slightly behind thread_create
        starter = await self._fetch_starter(thread)
        if starter is None:
            await asyncio.sleep(1.5)
            starter = await self._fetch_starter(thread)
        if starter is None:
            logger.warning("censor: no starter message for thread %s", thread.id)
            return

        if starter.author.bot:
            return

        _mark_processed(thread.id)

        title = thread.name or ""
        body = starter.content or ""
        has_attachments = bool(starter.attachments) or bool(starter.stickers)
        attachment_only = has_attachments and len(body.strip()) < 20

        llm = self.bot.gemini  # type: ignore[attr-defined]
        result = await asyncio.to_thread(
            censor_post,
            llm,
            title=title,
            body=body,
            has_attachments=has_attachments,
            attachment_only=attachment_only,
        )
        logger.info(
            "censor thread=%s allowed=%s source=%s reason=%r",
            thread.id,
            result.allowed,
            result.source,
            result.reason[:120],
        )

        if result.allowed:
            try:
                await starter.add_reaction(_ALLOW_EMOJI)
            except discord.HTTPException:
                logger.warning("censor: could not react on %s", thread.id)
            return

        await self._reject(thread, starter.author, result.reason)

    async def _reject(
        self,
        thread: discord.Thread,
        author: discord.abc.User,
        reason: str,
    ) -> None:
        deleted = False
        try:
            await thread.delete(reason=f"chia-sẻ censor: {reason[:180]}")
            deleted = True
            logger.info("censor: deleted thread %s", thread.id)
        except discord.Forbidden:
            logger.warning("censor: no permission to delete thread %s — locking", thread.id)
        except discord.HTTPException:
            logger.exception("censor: delete failed for %s — locking", thread.id)

        if not deleted:
            try:
                await thread.edit(locked=True, archived=False, reason="chia-sẻ censor fallback")
            except discord.HTTPException:
                logger.exception("censor: lock failed for %s", thread.id)
            try:
                await thread.send(
                    f"{author.mention} Bài này **không đạt** kiểm duyệt chia-sẻ.\n"
                    f"**Lý do:** {reason}\n"
                    "_Thread đã bị khóa (bot chưa có quyền xóa)._"
                )
            except discord.HTTPException:
                logger.exception("censor: could not post reject notice in %s", thread.id)

        if deleted:
            notice = (
                f"Bài «{thread.name}» của bạn trên **chia-sẻ** đã bị **xóa** "
                f"vì không đạt kiểm duyệt.\n"
                f"**Lý do:** {reason}\n"
                "Hãy chỉnh nội dung rồi đăng lại nhé."
            )
        else:
            notice = (
                f"Bài «{thread.name}» của bạn trên **chia-sẻ** đã bị **khóa** "
                f"vì không đạt kiểm duyệt.\n"
                f"**Lý do:** {reason}\n"
                "Hãy chỉnh nội dung rồi đăng lại nhé."
            )
        await self._dm_author(thread.guild, author, notice)

    async def _dm_author(
        self,
        guild: discord.Guild | None,
        author: discord.abc.User,
        notice: str,
    ) -> None:
        target: discord.abc.User = author
        if guild is not None:
            member = guild.get_member(author.id)
            if member is None:
                try:
                    member = await guild.fetch_member(author.id)
                except discord.HTTPException:
                    member = None
            if member is not None:
                target = member
        try:
            await target.send(notice)
            logger.info("censor: DM sent to user %s", author.id)
        except discord.Forbidden:
            logger.warning(
                "censor: cannot DM user %s (DMs closed or privacy settings)",
                author.id,
            )
        except discord.HTTPException:
            logger.exception("censor: DM failed for user %s", author.id)

    async def _fetch_starter(self, thread: discord.Thread) -> discord.Message | None:
        try:
            return await thread.fetch_message(thread.id)
        except (discord.NotFound, discord.HTTPException):
            pass
        try:
            async for msg in thread.history(limit=1, oldest_first=True):
                return msg
        except discord.HTTPException:
            return None
        return None


def _mark_processed(thread_id: int) -> None:
    _PROCESSED.add(thread_id)
    if len(_PROCESSED) > _PROCESSED_MAX:
        # Drop arbitrary oldest-ish batch
        for tid in list(_PROCESSED)[: _PROCESSED_MAX // 5]:
            _PROCESSED.discard(tid)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ForumCensor(bot))
