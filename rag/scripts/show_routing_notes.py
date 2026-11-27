"""Lists the routing notes (proposed actions) in the review queue, newest first.
Run from the rag folder: uv run python scripts/show_routing_notes.py
It reads with the desk_service login and changes nothing."""
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()
with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    rows = conn.execute(
        "select created_at, case_id, status, proposed->>'tool', proposed->'args', left(summary, 80) "
        "from ops.review_items where kind = 'proposed_action' order by created_at desc limit 10").fetchall()
for r in rows:
    print(" | ".join(str(x) for x in r))
print(f"{len(rows)} routing note(s)")
