import os
import psycopg
from dotenv import load_dotenv

load_dotenv()
url = os.environ["DATABASE_URL"]

with psycopg.connect(url) as conn:
    with conn.cursor() as cur:
        cur.execute("select version()")
        print("connected:", cur.fetchone()[0][:60])
        cur.execute("select name, default_version from pg_available_extensions where name = 'vector'")
        print("pgvector available:", cur.fetchone())