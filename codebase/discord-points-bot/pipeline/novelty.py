"""B4 — novelty grading (D1) via gemini-2.5-flash."""

from __future__ import annotations

from ai.gemini_client import GeminiClient
from pipeline.models import NoveltyResult, NormalizedPost, RelatedPost

SYSTEM = """Bạn là trợ lý chấm điểm tính mới cho bài viết học viên trên Discord.
So với KHO BÀI ĐÃ POST trên server, KHÔNG so với kiến thức phổ thông.
Trả JSON đúng schema, không markdown.
Thang điểm:
0-2 trùng ý bài đã có; 3-5 cùng chủ đề nhưng bổ sung dữ liệu/ví dụ;
6-8 góc nhìn khác hoặc phản biện; 9-10 vấn đề chưa ai nêu trên server.
Nếu chấm thấp (<6) BẮT BUỘC related_post_ids trỏ tới id bài đã cho trong ngữ cảnh.
Nếu không chỉ ra được bài nào đã nói rồi thì KHÔNG được hạ điểm — đặt score>=6 và needs_review=true.
"""


async def grade_novelty(
    client: GeminiClient,
    post: NormalizedPost,
    related: list[RelatedPost],
) -> NoveltyResult:
    context_posts = [
        {
            "post_id": r.post_id,
            "title": r.title,
            "similarity": r.similarity,
            "excerpt": r.body_excerpt,
        }
        for r in related
    ]
    prompt = {
        "task": "score_novelty",
        "new_post": {
            "post_id": post.post_id,
            "title": post.title,
            "body": post.body[:6000],
        },
        "retrieved_similar_posts": context_posts,
        "output_schema": {
            "score": "number 0-10",
            "rationale": "string",
            "related_post_ids": ["post_id ..."],
            "needs_review": "boolean",
            "review_reason": "string|null",
        },
    }
    import json

    data = client.generate_json(
        json.dumps(prompt, ensure_ascii=False),
        system=SYSTEM,
    )
    score = float(data.get("score", 5))
    score = max(0.0, min(10.0, score))
    related_ids = [str(x) for x in data.get("related_post_ids") or []]
    return NoveltyResult(
        score=score,
        rationale=str(data.get("rationale") or ""),
        related_post_ids=related_ids,
        needs_review=bool(data.get("needs_review")),
        review_reason=data.get("review_reason"),
    )
