import os

import psycopg
from dotenv import load_dotenv

load_dotenv()
with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    rows = conn.execute(
        "select conname, pg_get_constraintdef(oid) from pg_constraint "
        "where conrelid = 'documents'::regclass and contype = 'c' order by conname"
    ).fetchall()
for name, definition in rows:
    print(name)
    print("   ", definition)