"""B2 — normalize text + interaction metadata helpers."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from pipeline.models import InteractionMeta, NormalizedPost


def week_key_from_iso(created_at: str | None) -> str:
    if not created_at:
        dt = datetime.now(timezone.utc)
    else:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    iso = dt.astimezone(timezone.utc).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def normalize_text(title: str, body: str) -> tuple[str, str]:
    title_n = re.sub(r"\s+", " ", (title or "").strip())
    body_n = (body or "").replace("\r\n", "\n").strip()
    body_n = re.sub(r"\n{3,}", "\n\n", body_n)
    return title_n, body_n


def raw_engagement(
    *,
    reaction_count: int,
    reply_count: int,
    unique_repliers: int,
    reply_depth: int,
) -> float:
    return (
        reaction_count * 1.0
        + reply_count * 1.5
        + unique_repliers * 2.0
        + reply_depth * 0.5
    )


def build_normalized_post(
    *,
    post_id: str,
    channel_id: str,
    author_id: str,
    author_name: str,
    title: str,
    body: str,
    created_at: str | None,
    url: str | None,
    reaction_count: int,
    reply_count: int,
    unique_repliers: int,
    reply_depth: int,
) -> NormalizedPost:
    title_n, body_n = normalize_text(title, body)
    engagement = raw_engagement(
        reaction_count=reaction_count,
        reply_count=reply_count,
        unique_repliers=unique_repliers,
        reply_depth=reply_depth,
    )
    return NormalizedPost(
        post_id=post_id,
        channel_id=channel_id,
        author_id=author_id,
        author_name=author_name,
        title=title_n,
        body=body_n,
        created_at=created_at,
        week_key=week_key_from_iso(created_at),
        url=url,
        interaction=InteractionMeta(
            reaction_count=reaction_count,
            reply_count=reply_count,
            unique_repliers=unique_repliers,
            reply_depth=reply_depth,
            raw_engagement=engagement,
        ),
    )
