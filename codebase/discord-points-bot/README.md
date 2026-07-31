# Discord AI Grading Bot (v0.1)

Bot chấm bài trên forum `chia-sẻ` theo AI rubric. Điểm lưu vào SQLite;
user xem bằng `/mypoints`, admin xem bảng xếp hạng bằng `/report`.

## Rubric

| Tiêu chí | Trọng số | Cách chấm |
|---|---|---|
| Tính mới | 40% | embedding truy hồi 8 bài giống → `google/gemini-2.5-flash` (OpenRouter) |
| Chất lượng | 40% | LLM 4 trục + evidence nguyên văn |
| Tương tác | 20% | Discord API, z-score theo tuần; trần +1.5 |

## Setup

```bash
cd codebase/discord-points-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# điền DISCORD_TOKEN, GUILD_ID, FORUM_CHANNEL_ID, OPENROUTER_API_KEY
python bot.py
```

AI qua **OpenRouter**:
- Chat: `google/gemini-2.5-flash`
- Embeddings: `openai/text-embedding-3-small`

## Cycle (every 3 minutes by default)

1. Sync new/updated posts from `chia-sẻ` → `posts_history`
2. AI-score any posts not graded yet → `grades`
3. `/mypoints` & `/report` read updated averages from `grades`

| Lệnh | Ai | Việc |
|---|---|---|
| Gõ câu hỏi bình thường | mọi người | Bot reply nếu giống câu hỏi (không cần slash); cũng reply khi @bot |
| `/mypoints` | mọi người | Điểm AI rubric + hạng |
| `/report` | Admin | Bảng xếp hạng + CSV |
| `/syncnow` | Admin | Backfill history + embeddings |
| `/regrade <thread_id>` | Admin | Chấm lại một bài (lưu DB) |
| _(auto)_ | — | Post mới → chấm → lưu DB |
