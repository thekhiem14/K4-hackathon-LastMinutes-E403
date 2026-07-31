"""Display helpers for AI-rubric /mypoints and /report."""

from __future__ import annotations

from db.database import UserGradeStats


def breakdown_lines(stats: UserGradeStats) -> list[tuple[str, str]]:
    return [
        ("Bài đã chấm (AI)", str(stats.graded_posts)),
        ("Tính mới (TB · 40%)", f"{stats.avg_novelty:.1f}/10"),
        ("Chất lượng (TB · 40%)", f"{stats.avg_quality:.1f}/10"),
        ("Tương tác (TB · 20%)", f"{stats.avg_interaction:.1f}/10"),
        (
            "Bài bị flag",
            str(stats.needs_review_posts) if stats.needs_review_posts else "0",
        ),
    ]
