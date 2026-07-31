"""Chat with users via @mention; remember recent turns (1 MiB total budget)."""

from __future__ import annotations

import asyncio
import logging
import re
import time

import discord
from discord.ext import commands

from cogs.chat_memory import ConversationMemory
from db.database import Database

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Bạn là trợ lý chat trên Discord lớp học AI.
Trả lời ngắn gọn, thân thiện, bằng tiếng Việt (trừ khi user hỏi tiếng Anh).

Bạn có lịch sử hội thoại gần đây với user này — dùng nó để nhớ ngữ cảnh
(ví dụ "bài đó", "điểm vừa nói").

Bạn cũng được cung cấp dữ liệu thật từ database (điểm user, bài post, điểm AI).
- Khi hỏi về bài / điểm / xếp hạng: CHỈ dùng dữ liệu DB trong message hiện tại.
- Không bịa tiêu đề bài hoặc điểm nếu không có trong context.
- Nếu DB không có bài phù hợp: nói rõ là chưa tìm thấy trong kho đã sync.
- Rubric: tính mới 40%, chất lượng 40%, tương tác 20% (trần +1.5).
- Không bịa deadline/link nộp bài chính thức.
"""

_POST_TOPIC_RE = re.compile(
    r"(bài|post|chia[- ]?sẻ|viết về|ai đăng|ai viết|nội dung|"
    r"điểm bài|chấm|rubric|xếp hạng|leaderboard|top|"
    r"lightgbm|ocr|agent|token|machine learning|ml\b)",
    re.IGNORECASE,
)

_COOLDOWN_SECONDS = 4.0
_MEMORY_MAX_BYTES = 1_048_576  # 1 MiB total across all users


class AskCommands(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database) -> None:
        self.bot = bot
        self.db = db
        self._last_reply_at: dict[int, float] = {}
        self._memory = ConversationMemory(max_bytes=_MEMORY_MAX_BYTES)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Chat is handled from GradingBot.on_message → handle_mention
        # (kept as no-op listener so cog still registers cleanly)
        return

    async def handle_mention(self, message: discord.Message) -> None:
        if message.author.bot or self.bot.user is None:
            return
        if not message.guild:
            return
        if message.guild.id != self.bot.settings.guild_id:  # type: ignore[attr-defined]
            return
        if not _message_mentions_bot(message, self.bot.user, message.guild.me):
            return

        forum_id = self.bot.settings.forum_channel_id  # type: ignore[attr-defined]
        in_forum = getattr(message.channel, "id", None) == forum_id
        in_forum_thread = (
            isinstance(message.channel, discord.Thread)
            and message.channel.parent_id == forum_id
        )
        if in_forum or in_forum_thread:
            await message.reply(
                "Mình không chat trong kênh/thread **chia-sẻ**. "
                "Hãy @ mình ở channel text khác (ví dụ #general).",
                mention_author=False,
            )
            return

        question = _strip_bot_mention(message.content, self.bot.user, message.guild.me)
        if not question:
            await message.reply(
                "Bạn @ mình rồi — hỏi gì nào? (ví dụ điểm bài, xếp hạng, giải thích rubric)",
                mention_author=False,
            )
            return

        if self.bot.gemini is None:  # type: ignore[attr-defined]
            await message.reply(
                "Bot chưa cấu hình OPENROUTER_API_KEY nên chưa chat được.",
                mention_author=False,
            )
            return

        now = time.monotonic()
        last = self._last_reply_at.get(message.author.id, 0.0)
        if now - last < _COOLDOWN_SECONDS:
            logger.info("chat cooldown skip user=%s", message.author.id)
            return
        self._last_reply_at[message.author.id] = now

        history = self._memory.history(message.author.id)
        logger.info(
            "chat reply start user=%s channel=%s hist_turns=%s mem=%s/%s q=%r",
            message.author.id,
            message.channel.id,
            len(history),
            self._memory.used_bytes,
            _MEMORY_MAX_BYTES,
            question[:120],
        )
        async with message.channel.typing():
            try:
                answer = await self._answer(message.author, question, history)
            except Exception:
                logger.exception("chat reply failed")
                await message.reply(
                    "Xin lỗi, mình gặp lỗi khi trả lời. Thử lại sau nhé.",
                    mention_author=False,
                )
                return

        await message.reply(answer[:1900], mention_author=False)
        self._memory.append(message.author.id, "user", question)
        self._memory.append(message.author.id, "assistant", answer[:1900])
        logger.info(
            "chat reply ok user=%s mem=%s/%s",
            message.author.id,
            self._memory.used_bytes,
            _MEMORY_MAX_BYTES,
        )

    async def _answer(
        self,
        user: discord.abc.User,
        question: str,
        history: list[dict[str, str]],
    ) -> str:
        db_context = await self._build_db_context(
            question,
            str(user.id),
            getattr(user, "display_name", user.name),
        )
        prompt = (
            f"User: {getattr(user, 'display_name', user.name)}\n\n"
            f"=== DỮ LIỆU TỪ DATABASE ===\n{db_context}\n"
            f"=== HẾT DỮ LIỆU ===\n\n"
            f"Tin nhắn user:\n{question}"
        )
        llm = self.bot.gemini  # type: ignore[attr-defined]
        return await asyncio.to_thread(
            llm.generate_text,
            prompt,
            system=SYSTEM_PROMPT,
            history=history,
            max_tokens=1024,
            temperature=0.4,
        )

    async def _build_db_context(
        self,
        question: str,
        user_id: str,
        display_name: str,
    ) -> str:
        parts: list[str] = []

        stats = await self.db.fetch_user_stats(user_id)
        if stats is None:
            parts.append(f"Điểm của {display_name}: chưa có bài graded.")
        else:
            parts.append(
                f"Điểm của {display_name}: hạng #{stats.rank}, "
                f"tổng TB {stats.avg_total:.2f}, "
                f"mới {stats.avg_novelty:.1f}, CL {stats.avg_quality:.1f}, "
                f"TT {stats.avg_interaction:.1f}, {stats.graded_posts} bài."
            )

        wants_posts = bool(_POST_TOPIC_RE.search(question)) or bool(
            re.search(r"(bài|post|điểm|xếp hạng|ai viết|viết về)", question, re.I)
        )
        wants_rank = bool(
            re.search(r"(xếp hạng|leaderboard|top\b|ai cao|hạng bao)", question, re.I)
        )

        if wants_rank:
            board = await self.db.fetch_leaderboard(limit=8)
            if board:
                lines = [
                    f"#{e.rank} {e.display_name}: {e.avg_total:.2f} "
                    f"(mới {e.avg_novelty:.1f}, CL {e.avg_quality:.1f}, "
                    f"TT {e.avg_interaction:.1f}, {e.graded_posts} bài)"
                    for e in board
                ]
                parts.append("Bảng xếp hạng (top):\n" + "\n".join(lines))
            else:
                parts.append("Bảng xếp hạng: chưa có dữ liệu graded.")

        if wants_posts or wants_rank:
            posts = await self.db.search_posts(question, limit=5)
            if not posts:
                posts = await self.db.list_recent_posts(limit=5)
                parts.append("(Không khớp từ khóa — lấy 5 bài gần nhất)")
            post_blocks: list[str] = []
            for p in posts:
                grade = await self.db.latest_grade_for_post(p.post_id)
                excerpt = re.sub(r"\s+", " ", p.body).strip()[:280]
                grade_line = "chưa chấm"
                if grade and grade.get("total_score") is not None:
                    grade_line = (
                        f"status={grade['status']} total={grade['total_score']:.2f} "
                        f"(mới={grade.get('novelty_score')}, "
                        f"CL={grade.get('quality_score')}, "
                        f"TT={grade.get('interaction_score')})"
                    )
                elif grade:
                    grade_line = (
                        f"status={grade['status']} "
                        f"reason={grade.get('escalate_reason') or '—'}"
                    )
                post_blocks.append(
                    f"- id={p.post_id} | {p.author_name} | «{p.title}»\n"
                    f"  reactions={p.reaction_count} replies={p.reply_count}\n"
                    f"  grade: {grade_line}\n"
                    f"  excerpt: {excerpt}"
                )
            parts.append("Bài viết liên quan từ DB:\n" + "\n".join(post_blocks))

        return "\n\n".join(parts) if parts else "DB trống."


def _strip_bot_mention(
    content: str,
    bot_user: discord.ClientUser,
    me: discord.Member | None = None,
) -> str:
    text = content.replace(f"<@{bot_user.id}>", " ")
    text = text.replace(f"<@!{bot_user.id}>", " ")
    if me is not None:
        for role in me.roles:
            if role.is_default():
                continue
            text = text.replace(f"<@&{role.id}>", " ")
    return re.sub(r"\s+", " ", text).strip()


def _message_mentions_bot(
    message: discord.Message,
    bot_user: discord.ClientUser,
    me: discord.Member | None = None,
) -> bool:
    if any(u.id == bot_user.id for u in message.mentions):
        return True
    content = message.content or ""
    if f"<@{bot_user.id}>" in content or f"<@!{bot_user.id}>" in content:
        return True
    # Users often @ the bot's role (looks similar in Discord UI)
    if me is not None and message.role_mentions:
        bot_roles = {r.id for r in me.roles if not r.is_default()}
        if any(r.id in bot_roles for r in message.role_mentions):
            return True
    return False


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AskCommands(bot, bot.db))  # type: ignore[attr-defined]
