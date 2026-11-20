import os
import re

import psycopg
from dotenv import load_dotenv

from ingest.embed import embed_query

load_dotenv()

# Only approved documents may answer questions.
ALLOWED_STATUSES = ["approved"]

# Price intent only. "annual" or "monthly" alone is not enough, because
# "Can I cancel my annual plan?" is a policy question.
PRICE_RE = re.compile(
    r"\b(price|prices|pricing|cost|costs|how much|fee|fees|per month|per year)\b", re.I)

PLAN_PATTERNS = {
    "Starter": r"\bstarter\b",
    "Pro": r"\bpro\b",
    "Team": r"\bteam\b",
    "Extra seat": r"\bextra seats?\b",
}
CURRENCY_PATTERNS = {
    "EUR": r"\b(eur|euros?)\b|â‚¬",
    "USD": r"\b(usd|dollars?)\b|\$",
    "INR": r"\b(inr|rupees?)\b|â‚¹",
}


def route(question: str) -> str:
    return "sql" if (PRICE_RE.search(question) or any(re.search(p, question, re.I) for p in {**EXTRA_SEAT_PATTERN, **PLAN_PATTERNS}.values())) else "vector"


EXTRA_SEAT_PATTERN = {"Extra seat": r"\b(extra|additional|add-on)\s+(team\s+)?seats?\b"}


def price_lookup(question: str) -> list[tuple]:
    where, params = [], []
    for plan, pattern in {**EXTRA_SEAT_PATTERN, **{k: v for k, v in PLAN_PATTERNS.items() if k not in EXTRA_SEAT_PATTERN}}.items():
        if re.search(pattern, question, re.I):
            where.append("plan = %s")
            params.append(plan)
            break
    for currency, pattern in CURRENCY_PATTERNS.items():
        if re.search(pattern, question, re.I):
            where.append("currency = %s")
            params.append(currency)
            break
    if re.search(r"\b(year|yearly|annual|annually)\b", question, re.I):
        where.append("billing = 'annual'")
    elif re.search(r"\bmonth(ly)?\b", question, re.I):
        where.append("billing = 'monthly'")
    sql = "select plan, billing, currency, price, note from plans_fees"
    if where:
        sql += " where " + " and ".join(where)
    sql += " order by plan, billing, currency"
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        return conn.execute(sql, params).fetchall()


def vector_search(question: str, k: int = 5, approved_only: bool = True) -> list[tuple]:
    """Return (doc_id, clause_id, status, content, score) rows, best first.

    approved_only=True goes through the database function search_policy(), the single
    guarded door: the status filter lives there and cannot be skipped.
    approved_only=False is the evaluation-only unfiltered path (rag_off and the probe).
    It reads the tables directly as the database owner and must never serve a customer.
    """
    vec = "[" + ",".join(f"{x:.6f}" for x in embed_query(question)) + "]"
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        if approved_only:
            return conn.execute(
                "select doc_id, clause_id, status, content, score "
                "from search_policy(%s::vector, %s)",
                (vec, k),
            ).fetchall()
        sql = (
            "select c.doc_id, c.clause_id, d.status, c.content, "
            "1 - (c.embedding <=> %s::vector) as score "
            "from chunks c join documents d on d.doc_id = c.doc_id "
            "order by c.embedding <=> %s::vector, d.authority_rank limit %s"
        )
        return conn.execute(sql, (vec, vec, k)).fetchall()


XREF = re.compile(r"\bSection (\d+\.\d+)")


def expand_references(rows: list[tuple], approved_only: bool = True) -> list[tuple]:
    """Add clauses that a retrieved clause points to ("Section 3.5") from the same document.

    Rows keep the (doc_id, clause_id, status, content, score) shape; added rows have score None.
    One level only: a clause pulled in this way is not itself expanded.
    """
    have = {(r[0], r[1]) for r in rows}
    wanted = []
    for doc_id, clause_id, _status, content, _score in rows:
        if not clause_id:
            continue
        for ref in XREF.findall(content):
            if (doc_id, ref) not in have and (doc_id, ref) not in wanted:
                wanted.append((doc_id, ref))
    if not wanted:
        return rows
    sql = ("select c.doc_id, c.clause_id, d.status, c.content from chunks c "
           "join documents d on d.doc_id = c.doc_id where c.doc_id = %s and c.clause_id = %s")
    if approved_only:
        sql += " and d.status = any(%s)"
    extra = []
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        for doc_id, ref in wanted:
            params = (doc_id, ref, ALLOWED_STATUSES) if approved_only else (doc_id, ref)
            for doc, clause, status, content in conn.execute(sql, params).fetchall():
                extra.append((doc, clause, status, content, None))
    return rows + extra

QUESTIONS = [
    "How much does the Pro plan cost per month in euros?",
    "What is the price of the Team plan on annual billing in USD?",
    "How long do I have to ask for a refund?",
    "Can I cancel my annual plan?",
    "What happens during a payment dispute?",
]

if __name__ == "__main__":
    for question in QUESTIONS:
        path = route(question)
        print(f"\n[{path.upper()}] {question}")
        if path == "sql":
            for plan, billing, currency, price, source in price_lookup(question):
                print(f"   {plan} | {billing} | {currency} | {price}   ({source})")
        else:
            for label, flag in (("filter OFF", False), ("filter ON ", True)):
                print(f"  {label}")
                for doc_id, clause_id, status, content, score in vector_search(
                        question, 4, approved_only=flag):
                    print(f"   {score:.3f}  {doc_id:20} {str(clause_id):5} "
                          f"{status:11} {content[:50]}")