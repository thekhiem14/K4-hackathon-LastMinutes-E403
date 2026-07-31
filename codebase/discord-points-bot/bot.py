"""
Discord AI Grading Bot — grades forum posts with the AI rubric.

Every SYNC_INTERVAL_MINUTES (default 3):
  1) Sync new posts from chia-sẻ into posts_history
  2) Score any posts that are not graded yet
  3) Student scores (/mypoints, /report) update from the grades table
"""

from __future__ import annotations

import asyncio
import logging
import traceback

import discord
from discord.ext import commands, tasks

from ai.openrouter_client import OpenRouterClient
from cogs.ask_commands import AskCommands
from cogs.coach_commands import CoachCommands
from cogs.points_commands import PointsCommands
from config import Settings, load_settings
from db.database import Database
from pipeline.normalize import build_normalized_post
from pipeline.run import run_grading_pipeline
from sync.forum_sync import sync_forum_history, thread_to_normalized

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("grading_bot")


class GradingBot(commands.Bot):
    def __init__(
        self,
        settings: Settings,
        db: Database,
        gemini: OpenRouterClient | None,
    ) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.guild_messages = True
        intents.reactions = True
        intents.message_content = True

        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.db = db
        self.gemini = gemini
        self._cycle_lock: asyncio.Lock | None = None

    async def setup_hook(self) -> None:
        self._cycle_lock = asyncio.Lock()
        await self.add_cog(CoachCommands(self))
        await self.add_cog(PointsCommands(self, self.db))
        await self.add_cog(AskCommands(self, self.db))

        guild = discord.Object(id=self.settings.guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        logger.info("Synced %s guild slash command(s)", len(synced))

        minutes = self.settings.sync_interval_minutes
        self.periodic_cycle.change_interval(minutes=minutes)
        self.periodic_cycle.start()
        logger.info("Periodic sync+grade cycle every %s minute(s)", minutes)

    async def close(self) -> None:
        if self.periodic_cycle.is_running():
            self.periodic_cycle.cancel()
        await self.db.close()
        await super().close()

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (%s)", self.user, self.user and self.user.id)
        logger.info("Loaded cogs: %s", list(self.cogs.keys()))
        guild = self.get_guild(self.settings.guild_id)
        if guild and self.user:
            me = guild.me
            for ch in guild.text_channels:
                perms = ch.permissions_for(me)
                if ch.name.lower() in {"general", "chat", "bot"} or not perms.view_channel:
                    logger.info(
                        "Channel #%s view=%s send=%s read_history=%s",
                        ch.name,
                        perms.view_channel,
                        perms.send_messages,
                        perms.read_message_history,
                    )
        self.loop.create_task(self.run_cycle(reason="startup"))

    async def on_message(self, message: discord.Message) -> None:
        if (
            message.guild
            and message.guild.id == self.settings.guild_id
            and self.user is not None
            and not message.author.bot
        ):
            ch_name = getattr(message.channel, "name", str(message.channel.id))
            me = message.guild.me
            mentioned = _is_bot_ping(message, self.user, me)
            logger.info(
                "msg channel=#%s author=%s mentioned=%s content=%r",
                ch_name,
                message.author.id,
                mentioned,
                (message.content or "")[:160],
            )
            if mentioned:
                ask = self.get_cog("AskCommands")
                if ask is None:
                    logger.error("AskCommands cog not loaded — cogs=%s", list(self.cogs.keys()))
                    try:
                        await message.reply(
                            "Chat chưa sẵn sàng (cog missing). Restart bot giúp mình.",
                            mention_author=False,
                        )
                    except discord.HTTPException:
                        pass
                else:
                    await ask.handle_mention(message)  # type: ignore[attr-defined]
        await self.process_commands(message)

    @tasks.loop(minutes=3)
    async def periodic_cycle(self) -> None:
        await self.run_cycle(reason="scheduled")

    @periodic_cycle.before_loop
    async def before_periodic_cycle(self) -> None:
        await self.wait_until_ready()

    async def run_forum_sync(self, *, reason: str) -> int | None:
        """Used by /syncnow — runs the full sync+grade cycle."""
        return await self.run_cycle(reason=reason)

    async def run_cycle(self, *, reason: str) -> int | None:
        """Sync forum → grade new posts → student scores refresh via DB."""
        if self._cycle_lock is None:
            return None
        if self._cycle_lock.locked():
            logger.info("Cycle skipped (%s) — already running", reason)
            return None

        async with self._cycle_lock:
            guild = self.get_guild(self.settings.guild_id)
            if guild is None:
                logger.error("Guild %s not found", self.settings.guild_id)
                return None
            channel = guild.get_channel(self.settings.forum_channel_id)
            if channel is None:
                try:
                    channel = await guild.fetch_channel(self.settings.forum_channel_id)
                except discord.HTTPException as exc:
                    logger.error("Cannot fetch forum: %s", exc)
                    return None
            if not isinstance(channel, discord.ForumChannel):
                logger.error("FORUM_CHANNEL_ID is not a ForumChannel")
                return None

            logger.info("Cycle start (%s): sync posts…", reason)
            try:
                posts_synced = await sync_forum_history(
                    guild=guild,
                    forum=channel,
                    db=self.db,
                    gemini=self.gemini,
                    embed_missing=True,
                )
            except Exception:
                logger.error("Sync failed\n%s", traceback.format_exc())
                return None

            graded = await self._grade_ungraded_posts(guild)
            logger.info(
                "Cycle done (%s): synced=%s newly_graded=%s",
                reason,
                posts_synced,
                graded,
            )
            return posts_synced

    async def _grade_ungraded_posts(self, guild: discord.Guild) -> int:
        if self.gemini is None:
            logger.warning("Skip grading — OPENROUTER_API_KEY not set")
            return 0

        missing = await self.db.posts_missing_grades()
        if not missing:
            logger.info("No ungraded posts")
            return 0

        logger.info("Grading %s ungraded post(s)…", len(missing))
        graded = 0
        for post in missing:
            try:
                thread = guild.get_thread(int(post.post_id))
                if thread is None:
                    try:
                        fetched = await guild.fetch_channel(int(post.post_id))
                    except (discord.HTTPException, ValueError):
                        fetched = None
                    thread = fetched if isinstance(fetched, discord.Thread) else None

                if thread is not None:
                    normalized, has_attach, attach_only = await thread_to_normalized(
                        thread,
                        self.settings.forum_channel_id,
                    )
                else:
                    # Fall back to DB snapshot if thread is gone/inaccessible
                    normalized = build_normalized_post(
                        post_id=post.post_id,
                        channel_id=post.channel_id,
                        author_id=post.author_id,
                        author_name=post.author_name,
                        title=post.title,
                        body=post.body,
                        created_at=post.created_at,
                        url=None,
                        reaction_count=post.reaction_count,
                        reply_count=post.reply_count,
                        unique_repliers=post.unique_repliers,
                        reply_depth=post.reply_depth,
                    )
                    has_attach = False
                    attach_only = False

                grade = await run_grading_pipeline(
                    db=self.db,
                    gemini=self.gemini,
                    post=normalized,
                    has_attachments=has_attach,
                    attachment_only=attach_only,
                )
                graded += 1 if grade.status == "graded" and grade.total_score is not None else 0
                logger.info(
                    "Graded %s (%s) → status=%s total=%s",
                    post.post_id,
                    post.title[:40],
                    grade.status,
                    grade.total_score,
                )
            except Exception:
                logger.error(
                    "Failed grading post %s\n%s",
                    post.post_id,
                    traceback.format_exc(),
                )
        return graded


def main() -> None:
    settings = load_settings()
    db = Database(settings.database_path)
    llm = None
    if settings.openrouter_api_key:
        llm = OpenRouterClient(
            settings.openrouter_api_key,
            chat_model=settings.chat_model,
            embed_model=settings.embed_model,
        )
    else:
        logger.warning("OPENROUTER_API_KEY missing — AI grading disabled until set")

    async def runner() -> None:
        await db.connect()
        bot = GradingBot(settings, db, llm)
        async with bot:
            await bot.start(settings.token)

    asyncio.run(runner())


def _is_bot_ping(
    message: discord.Message,
    bot_user: discord.ClientUser,
    me: discord.Member | None,
) -> bool:
    if any(u.id == bot_user.id for u in message.mentions):
        return True
    content = message.content or ""
    if f"<@{bot_user.id}>" in content or f"<@!{bot_user.id}>" in content:
        return True
    # Discord UI looks similar for @role vs @bot — accept the bot's roles too
    if me is not None and message.role_mentions:
        bot_roles = {r.id for r in me.roles if not r.is_default()}
        if any(r.id in bot_roles for r in message.role_mentions):
            return True
    return False


if __name__ == "__main__":
    main()
