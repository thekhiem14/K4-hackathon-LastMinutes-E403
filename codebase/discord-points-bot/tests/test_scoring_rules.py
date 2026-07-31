"""Unit tests for scoring rules (no Discord / Gemini required)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.models import NoveltyResult, QualityAxis, QualityResult
from pipeline.prefilter import prefilter_post
from pipeline.score import compose_total, enforce_novelty_related_ids
from pipeline.verify import quote_in_source, verify_quality_evidence


class TestComposeTotal(unittest.TestCase):
    def test_interaction_cap(self) -> None:
        # novelty=10, quality=10 → content=8.0; interaction=10 → +2 uncapped
        content, capped, uncapped = compose_total(novelty=10, quality=10, interaction=10)
        self.assertAlmostEqual(content, 8.0)
        self.assertAlmostEqual(uncapped, 10.0)
        self.assertAlmostEqual(capped, 9.5)  # 8 + 1.5 cap

    def test_low_interaction_no_cap_hit(self) -> None:
        content, capped, uncapped = compose_total(novelty=5, quality=5, interaction=2)
        self.assertAlmostEqual(content, 4.0)
        self.assertAlmostEqual(uncapped, 4.4)
        self.assertAlmostEqual(capped, 4.4)


class TestNoveltyRule(unittest.TestCase):
    def test_low_score_without_related_needs_review(self) -> None:
        novelty = NoveltyResult(score=2, rationale="trùng", related_post_ids=["x"])
        out = enforce_novelty_related_ids(novelty, retrieved_ids={"a", "b"})
        self.assertTrue(out.needs_review)
        self.assertEqual(out.related_post_ids, [])

    def test_low_score_with_valid_related_ok(self) -> None:
        novelty = NoveltyResult(score=3, rationale="gần", related_post_ids=["a"])
        out = enforce_novelty_related_ids(novelty, retrieved_ids={"a", "b"})
        self.assertFalse(out.needs_review)
        self.assertEqual(out.related_post_ids, ["a"])


class TestEvidence(unittest.TestCase):
    def test_quote_must_be_substring(self) -> None:
        body = "Chúng tôi giảm token 22% nhờ cache prompt."
        self.assertTrue(quote_in_source("giảm token 22%", body))
        self.assertFalse(quote_in_source("tăng tốc 1000%", body))

    def test_verify_drops_fake_quotes(self) -> None:
        quality = QualityResult(
            axes=[
                QualityAxis(
                    name="Cụ thể",
                    score=8,
                    evidence=["giảm token 22%", "không có trong bài"],
                )
            ],
            score=8,
            rationale="ok",
        )
        check = verify_quality_evidence(
            "Chúng tôi giảm token 22% nhờ cache prompt.",
            "Tiêu đề",
            quality,
        )
        self.assertEqual(check.cleaned.axes[0].evidence, ["giảm token 22%"])
        self.assertTrue(check.ok)
        self.assertTrue(any("không có trong bài" in i for i in check.issues))


class TestPrefilter(unittest.TestCase):
    def test_short_escalates(self) -> None:
        r = prefilter_post(title="Hi", body="ngắn", has_attachments=False, attachment_only=False)
        self.assertFalse(r.ok)
        self.assertEqual(r.status, "escalated")

    def test_normal_passes(self) -> None:
        body = "A" * 100
        r = prefilter_post(title="Bài hay", body=body, has_attachments=False, attachment_only=False)
        self.assertTrue(r.ok)


if __name__ == "__main__":
    unittest.main()
