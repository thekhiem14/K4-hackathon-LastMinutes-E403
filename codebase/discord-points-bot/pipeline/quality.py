"""B5 — quality grading (D2) via gemini-2.5-flash."""

from __future__ import annotations

import json

from ai.gemini_client import GeminiClient
from pipeline.models import NormalizedPost, QualityAxis, QualityResult

SYSTEM = """Bạn chấm chất lượng bài viết học viên Discord.
Bốn trục, mỗi trục 0-10, quality_score = trung bình 4 trục:
- cu_the: có số liệu/ví dụ/tình huống thật hay nói chung
- chong_do: khẳng định có dẫn chứng/nguồn hay không
- cau_truc: mạch đọc được hay rời rạc
- huu_dung: người đọc rút ra hành động gì
Mỗi trục BẮT BUỘC kèm evidence: danh sách đoạn trích NGUYÊN VĂN từ bài (substring thật).
Trả JSON đúng schema, không markdown.
"""

AXIS_KEYS = [
    ("cu_the", "Cụ thể"),
    ("chong_do", "Chống đỡ"),
    ("cau_truc", "Cấu trúc"),
    ("huu_dung", "Hữu dụng"),
]


async def grade_quality(client: GeminiClient, post: NormalizedPost) -> QualityResult:
    prompt = {
        "task": "score_quality",
        "post": {
            "title": post.title,
            "body": post.body[:6000],
        },
        "output_schema": {
            "axes": {
                "cu_the": {"score": "0-10", "evidence": ["verbatim quote"]},
                "chong_do": {"score": "0-10", "evidence": ["verbatim quote"]},
                "cau_truc": {"score": "0-10", "evidence": ["verbatim quote"]},
                "huu_dung": {"score": "0-10", "evidence": ["verbatim quote"]},
            },
            "rationale": "string",
        },
    }
    data = client.generate_json(
        json.dumps(prompt, ensure_ascii=False),
        system=SYSTEM,
    )
    axes_raw = data.get("axes") or {}
    axes: list[QualityAxis] = []
    for key, label in AXIS_KEYS:
        item = axes_raw.get(key) or {}
        score = float(item.get("score", 5))
        score = max(0.0, min(10.0, score))
        evidence = [str(e) for e in (item.get("evidence") or []) if str(e).strip()]
        axes.append(QualityAxis(name=label, score=score, evidence=evidence))
    mean = sum(a.score for a in axes) / len(axes) if axes else 0.0
    return QualityResult(
        axes=axes,
        score=mean,
        rationale=str(data.get("rationale") or ""),
    )
