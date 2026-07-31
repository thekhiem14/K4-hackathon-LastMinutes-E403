"""Backfill forum posts into posts_history (+ optional embeddings)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import discord

from ai.gemini_client import GeminiClient
from db.database import CommentRecord, Database, PostRecord
from pipeline.normalize import week_key_from_iso

logger = logging.getLogger(__name__)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def sync_forum_history(
    *,
    guild: discord.Guild,
    forum: discord.ForumChannel,
    db: Database,
    gemini: GeminiClient | None = None,
    embed_missing: bool = True,
) -> int:
    started = _now()
    run_id = await db.begin_sync(started)
    posts_synced = 0
    try:
        threads: list[discord.Thread] = list(forum.threads)
        async for thread in forum.archived_threads(limit=None):
            threads.append(thread)

        seen: set[int] = set()
        for thread in threads:
            if thread.id in seen:
                continue
            seen.add(thread.id)
            if await _sync_thread(thread, forum.id, db):
                posts_synced += 1

        if gemini is not None and embed_missing:
            await _embed_missing(db, gemini)

        await db.commit()
        await db.finish_sync(
            run_id,
            finished_at=_now(),
            status="ok",
            posts_synced=posts_synced,
        )
        logger.info("History sync ok: %s posts (guild=%s)", posts_synced, guild.id)
        return posts_synced
    except Exception as exc:  # noqa: BLE001
        await db.finish_sync(
            run_id,
            finished_at=_now(),
            status="error",
            posts_synced=posts_synced,
            error=str(exc),
        )
        logger.exception("History sync failed")
        raise


async def _iter_messages(thread: discord.Thread) -> AsyncIterator[discord.Message]:
    try:
        async for message in thread.history(limit=None, oldest_first=True):
            yield message
        return
    except (discord.Forbidden, discord.HTTPException):
        if not thread.archived:
            return
    try:
        await thread.edit(archived=False)
    except (discord.Forbidden, discord.HTTPException):
        return
    try:
        async for message in thread.history(limit=None, oldest_first=True):
            yield message
    finally:
        try:
            await thread.edit(archived=True)
        except (discord.Forbidden, discord.HTTPException):
            pass


async def collect_thread_stats(
    thread: discord.Thread,
) -> tuple[str, str, int, int, int, int, bool, bool, list[CommentRecord]]:
    """Return title, body, reactions, replies, unique, depth, has_attach, attach_only, comments."""
    starter: discord.Message | None = None
    replies = 0
    unique: set[int] = set()
    depth = 0
    reaction_count = 0
    has_attach = False
    body = ""
    author_id = thread.owner_id
    comments: list[CommentRecord] = []

    async for message in _iter_messages(thread):
        if message.attachments:
            has_attach = True
        if message.author.bot:
            continue
        if starter is None or message.id == thread.id:
            starter = message
            body = message.content or ""
            reaction_count = 0
            for reaction in message.reactions:
                users = [u async for u in reaction.users()]
                reaction_count += sum(1 for u in users if u.id != message.author.id)
            continue
        if starter and message.id == starter.id:
            continue
        replies += 1
        unique.add(message.author.id)
        depth = max(depth, 1)
        display = getattr(message.author, "display_name", None) or message.author.name
        comments.append(
            CommentRecord(
                message_id=str(message.id),
                post_id=str(thread.id),
                author_id=str(message.author.id),
                author_name=display,
                created_at=_iso(message.created_at),
            )
        )

    title = thread.name or (body[:80] if body else "Untitled")
    attach_only = has_attach and len((body or "").strip()) < 40
    if author_id is None and starter is not None:
        author_id = starter.author.id
    return (
        title,
        body,
        reaction_count,
        replies,
        len(unique),
        depth,
        has_attach,
        attach_only,
        comments,
    )


async def _sync_thread(thread: discord.Thread, forum_id: int, db: Database) -> bool:
    title, body, reactions, replies, unique, depth, _ha, _ao, comments = (
        await collect_thread_stats(thread)
    )
    author = thread.owner
    author_id = str(thread.owner_id or (author.id if author else 0))
    author_name = (
        getattr(author, "display_name", None)
        or getattr(author, "name", None)
        or author_id
    )
    created = _iso(thread.created_at)
    post = PostRecord(
        post_id=str(thread.id),
        channel_id=str(forum_id),
        author_id=author_id,
        author_name=author_name,
        title=title,
        body=body,
        created_at=created,
        reaction_count=reactions,
        reply_count=replies,
        unique_repliers=unique,
        reply_depth=depth,
        week_key=week_key_from_iso(created),
    )
    await db.upsert_post(post, _now())
    await db.replace_comments_for_post(str(thread.id), comments, _now())
    return True


async def _embed_missing(db: Database, gemini: GeminiClient) -> None:
    missing = await db.posts_missing_embeddings()
    for post in missing:
        text = f"{post.title}\n\n{post.body}".strip()
        if len(text) < 20:
            continue
        try:
            vector = gemini.embed(text)
            await db.save_embedding(post.post_id, gemini.embed_model, vector, _now())
        except Exception:
            logger.exception("Failed embedding post %s", post.post_id)
    await db.commit()


async def thread_to_normalized(
    thread: discord.Thread,
    forum_id: int,
) -> tuple[object, bool, bool]:
    from pipeline.normalize import build_normalized_post

    title, body, reactions, replies, unique, depth, has_attach, attach_only, _comments = (
        await collect_thread_stats(thread)
    )
    author = thread.owner
    author_id = str(thread.owner_id or (author.id if author else 0))
    author_name = (
        getattr(author, "display_name", None)
        or getattr(author, "name", None)
        or author_id
    )
    created = _iso(thread.created_at)
    normalized = build_normalized_post(
        post_id=str(thread.id),
        channel_id=str(forum_id),
        author_id=author_id,
        author_name=author_name,
        title=title,
        body=body,
        created_at=created,
        url=thread.jump_url,
        reaction_count=reactions,
        reply_count=replies,
        unique_repliers=unique,
        reply_depth=depth,
    )
    return normalized, has_attach, attach_only
