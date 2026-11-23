"""Database access for the policy server. Connects with OPS_POLICY_DATABASE_URL (the policy_reader login), which can
run one function, public.search_policy(), and nothing else."""
import os

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv()


def _connect():
    return psycopg.connect(os.environ["OPS_POLICY_DATABASE_URL"], row_factory=dict_row)


def search(vector: list[float], k: int) -> list[dict]:
    """Approved clauses nearest to the vector, best first. The status filter lives inside the function."""
    vec = "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
    with _connect() as conn:
        return conn.execute(
            "select doc_id, clause_id, content, score from public.search_policy(%s::vector, %s)", (vec, k)
        ).fetchall()


def assert_login_role(expected: str) -> None:
    """Refuse to start if the database login is not the role this server is built for."""
    with _connect() as conn:
        actual = conn.execute("select current_user as u").fetchone()["u"]
    if actual != expected:
        raise SystemExit(f"Database login is {actual!r}, expected {expected!r}. Refusing to start.")
