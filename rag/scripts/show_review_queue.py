"""Lists the review queue, newest first. Run from the rag folder: uv run python scripts/show_review_queue.py"""
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()
with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    rows = conn.execute("select created_at, item_id, case_id, kind, reason, status, left(question, 50) "
                        "from ops.review_items order by created_at desc limit 20").fetchall()
for r in rows:
    print(" | ".join(str(x) for x in r))
print(f"{len(rows)} item(s)")
