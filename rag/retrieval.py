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

    approved_only=True applies the status filter inside the query, before ranking.
    """
    vec = "[" + ",".join(f"{x:.6f}" for x in embed_query(question)) + "]"
    sql = (
        "select c.doc_id, c.clause_id, d.status, c.content, "
        "1 - (c.embedding <=> %s::vector) as score "
        "from chunks c join documents d on d.doc_id = c.doc_id "
    )
    if approved_only:
        sql += "where d.status = any(%s) "
        params = (vec, ALLOWED_STATUSES, vec, k)
    else:
        params = (vec, vec, k)
    # Equal similarity: the more authoritative document comes first
    sql += "order by c.embedding <=> %s::vector, d.authority_rank limit %s"
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        return conn.execute(sql, params).fetchall()


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