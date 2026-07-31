"""Display helpers for AI-rubric /mypoints and /report."""

from __future__ import annotations

from db.database import UserGradeStats


def breakdown_lines(stats: UserGradeStats) -> list[tuple[str, str]]:
    return [
        ("Bài đã chấm (AI)", str(stats.graded_posts)),
        ("Tính mới (cộng dồn · 40%)", f"{stats.sum_novelty:.1f}"),
        ("Chất lượng (cộng dồn · 40%)", f"{stats.sum_quality:.1f}"),
        ("Tương tác (cộng dồn · 20%)", f"{stats.sum_interaction:.1f}"),
        (
            "Bài bị flag",
            str(stats.needs_review_posts) if stats.needs_review_posts else "0",
        ),
    ]
