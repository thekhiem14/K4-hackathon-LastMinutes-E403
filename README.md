# Nhóm E403 — Gác cổng tính mới cho kênh chia sẻ

**Hướng B — Trợ lý Học viên (Discord)** · Loại: tính năng mới
Lát cắt: coach lab chấm loạt bài mới trong kênh chia sẻ → bot quyết định bài này có nêu vấn đề chưa từng xuất hiện trong kho bài đã đăng hay chỉ lặp lại → trả điểm tính mới kèm trích dẫn nguyên văn và mã bài trùng để coach duyệt hoặc sửa.

Chi tiết: [`spec.md`](./spec.md)

## Thành viên

| Mã HV | Họ tên |
|---|---|
| 2A202601130 | Đỗ Đức Tiến |
| 2A202601468 | Phạm Thanh Hưng |
| 2A202601110 | Võ Quốc Huy |
| 2A202601036 | Nguyễn Thế Khiêm |
| 2A202601584 | Trương Công Cường |

## Phân công có tên

> ⬜ CẦN ĐIỀN TÊN — rubric R7 yêu cầu mỗi phần có tên người cụ thể, và tại CP5 một thành viên ngẫu nhiên phải giải thích được phần mang tên mình.

| Phần | Artifact | Người chịu trách nhiệm |
|---|---|---|
| Spec | `spec.md` | ⬜ |
| Evidence — mining Discord | `eval/mining/`, `spec.md` §1 | ⬜ |
| Evidence — khảo sát ≥20 người | `validation/survey-log.md` | ⬜ |
| Prompt + golden set | `eval/eval_cases.md`, `eval/eval_cases.jsonl` | ⬜ |
| Code prototype | `codebase/discord-points-bot/` | ⬜ |
| Demo + slide | `demo/`, `demo-slides.pdf` | ⬜ |
| Validation vòng user | `validation/feedback-log.md` | ⬜ |

## Cấu trúc repo

```
├── README.md            ← file này
├── spec.md              ← AI Spec §1-§9 (hạn cứng 23:59 N1)
├── demo-slides.pdf      ← slide 6 trang            ⬜ CHƯA CÓ
├── codebase/            ← prototype                ✅
├── eval/                ← golden set + kết quả     ⬜ CHƯA CÓ
├── validation/          ← feedback log             ⬜ CHƯA CÓ
├── reflection/          ← mỗi người 1 file         ⬜ CHƯA CÓ
├── demo/                ← prototype HTML           ✅
└── data/                ← data pack BTC cấp, KHÔNG commit (xem .gitignore)
```

## Chạy prototype

```bash
cd codebase/discord-points-bot
pip install -r requirements.txt
cp .env.example .env        # điền GEMINI_API_KEY, DISCORD_TOKEN
python bot.py
```

Chạy bộ eval:

```bash
python eval/run_eval.py --cases eval/eval_cases.jsonl --out eval/results_run1.md
```

## Lưu ý dữ liệu

`data/` là data pack BTC cấp, thuộc quy định bảo mật của khóa — đã đưa vào `.gitignore`, không commit vào repo nộp bài. Golden set trích từ data ghi **mã bài / mã hội thoại**, không dán nguyên văn dài.
