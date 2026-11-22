"""Write-side database access. Connects with OPS_WRITER_DATABASE_URL (the ops_writer login) and nothing else."""
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()


def connect() -> psycopg.Connection:
    # Used as `with connect() as conn:`. The transaction commits on a clean exit and rolls back on an error.
    return psycopg.connect(os.environ["OPS_WRITER_DATABASE_URL"])


def assert_login_role(expected: str) -> None:
    """Refuse to start if the database login is not the role this server was launched as."""
    with connect() as conn:
        actual = conn.execute("select current_user").fetchone()[0]
    if actual != expected:
        raise SystemExit(f"Database login is {actual!r}, expected {expected!r}. Refusing to start.")
