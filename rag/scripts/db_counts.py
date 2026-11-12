import os

import psycopg
from dotenv import load_dotenv

load_dotenv()

with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    for table in ["documents", "clause_registry", "chunks", "plans_fees"]:
        count = conn.execute(f"select count(*) from {table}").fetchone()[0]
        print(f"{table:16} {count}")