import os
import psycopg
from dotenv import load_dotenv

load_dotenv()

with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    with conn.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.tables "
            "where table_schema = 'public' order by table_name"
        )
        print("tables:", [r[0] for r in cur.fetchall()])

        cur.execute(
            "select count(*), "
            "max(price) filter (where plan = 'Pro' and billing = 'annual' and currency = 'INR') "
            "from plans_fees"
        )
        print("plans_fees (rows, Pro annual INR):", cur.fetchone())