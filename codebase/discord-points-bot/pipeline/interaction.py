"""B6 — interaction score via weekly z-score + content cap helpers in score.py."""

from __future__ import annotations

import statistics

from db.database import PostRecord
from pipeline.normalize import raw_engagement


def interaction_score_for_post(
    *,
    reaction_count: int,
    reply_count: int,
    unique_repliers: int,
    reply_depth: int,
    week_peers: list[PostRecord],
) -> float:
    """Map engagement to 0–10 using z-score within the same ISO week."""
    current = raw_engagement(
        reaction_count=reaction_count,
        reply_count=reply_count,
        unique_repliers=unique_repliers,
        reply_depth=reply_depth,
    )
    peer_values = [
        raw_engagement(
            reaction_count=p.reaction_count,
            reply_count=p.reply_count,
            unique_repliers=p.unique_repliers,
            reply_depth=p.reply_depth,
        )
        for p in week_peers
    ]
    if len(peer_values) < 2:
        # Absolute fallback when the week has too few posts for a z-score.
        return _clip(current / 2.0, 0.0, 10.0)

    mean = statistics.fmean(peer_values)
    stdev = statistics.pstdev(peer_values)
    if stdev < 1e-9:
        return 5.0
    z = (current - mean) / stdev
    # Center at 5, ~2 points per sigma.
    return _clip(5.0 + 2.0 * z, 0.0, 10.0)


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
