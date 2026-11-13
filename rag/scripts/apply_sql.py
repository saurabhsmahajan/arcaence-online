import os
import sys

import psycopg
from dotenv import load_dotenv

load_dotenv()
sql = open(sys.argv[1], encoding="utf-8-sig").read()
with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    conn.execute(sql)
    print("applied", sys.argv[1])
    for row in conn.execute("select plan, billing, currency, price, note from plans_fees where note is not null order by currency"):
        print(row)

