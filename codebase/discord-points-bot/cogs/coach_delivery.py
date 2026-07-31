"""Format coach-channel Discord embeds for draft grades."""

from __future__ import annotations

import discord

from pipeline.models import GradeResult, NormalizedPost

COLOR_GRADED = 0x4FD1A0
COLOR_REVIEW = 0xE39C6B
COLOR_ESCALATED = 0xE5697B


def grade_embed(post: NormalizedPost, grade: GradeResult) -> discord.Embed:
    if grade.status == "graded" and not grade.needs_review:
        color = COLOR_GRADED
        title = "✅ Điểm AI rubric"
    elif grade.status == "graded":
        color = COLOR_REVIEW
        title = "⚠️ Điểm AI (có cảnh báo)"
    else:
        color = COLOR_ESCALATED
        title = "⛔ Không chấm được"

    embed = discord.Embed(
        title=title,
        description=(
            f"**{post.title}**\n"
            f"Tác giả: `{post.author_name}`\n"
            + (f"[Mở bài]({post.url})\n" if post.url else "")
        ),
        color=color,
    )

    if grade.total_score is not None:
        embed.add_field(
            name="Tổng (đã trần tương tác)",
            value=f"**{grade.total_score:.2f}** / 10 quy đổi trọng số",
            inline=True,
        )
    if grade.content_score is not None:
        embed.add_field(
            name="Nội dung (mới+CL)",
            value=f"{grade.content_score:.2f}",
            inline=True,
        )
    if grade.interaction_score is not None:
        embed.add_field(
            name="Tương tác (0–10)",
            value=f"{grade.interaction_score:.2f}",
            inline=True,
        )

    if grade.novelty is not None:
        related = ", ".join(grade.novelty.related_post_ids[:5]) or "—"
        embed.add_field(
            name=f"Tính mới ({grade.novelty.score:.1f}/10) · 40%",
            value=f"{grade.novelty.rationale[:300] or '—'}\n`related`: {related}",
            inline=False,
        )

    if grade.quality is not None:
        lines = [f"{grade.quality.rationale[:200] or '—'}"]
        for axis in grade.quality.axes:
            ev = axis.evidence[0][:80] if axis.evidence else "(không có evidence)"
            lines.append(f"• **{axis.name}** {axis.score:.1f}: _{ev}_")
        embed.add_field(
            name=f"Chất lượng ({grade.quality.score:.1f}/10) · 40%",
            value="\n".join(lines)[:1000],
            inline=False,
        )

    if grade.related_posts:
        top = "\n".join(
            f"• `{r.post_id}` {r.title[:60]} (sim={r.similarity:.2f})"
            for r in grade.related_posts[:5]
        )
        embed.add_field(name="Top bài tương tự (truy hồi)", value=top, inline=False)

    if grade.escalate_reason:
        embed.add_field(name="Lý do / cần duyệt", value=grade.escalate_reason[:500], inline=False)

    if grade.evidence_issues:
        embed.add_field(
            name="Evidence check",
            value="\n".join(grade.evidence_issues[:5])[:500],
            inline=False,
        )

    embed.set_footer(text=f"post_id={post.post_id} · status={grade.status}")
    return embed
