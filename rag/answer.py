import os
import re

import psycopg
from anthropic import Anthropic
from dotenv import load_dotenv

from retrieval import price_lookup, route, vector_search

load_dotenv()

MODEL = "claude-haiku-5-5"
client = Anthropic()

# [tos_v3 2.2]  [schedule_ab_v3 B.2]  [plans_fees]
CITE_RE = re.compile(r"\[(\w+)(?:\s+([\w.]+))?\]")

RAG_SYSTEM = (
    "You answer questions about Arcaence Online, a fictional subscription platform.\n"
    "Rules:\n"
    "- Answer only from the sources below. Do not use outside knowledge.\n"
    "- After every statement that uses a source, cite it in square brackets exactly "
    "as its label, for example [tos_v3 2.2] or [plans_fees].\n"
    "- If the sources do not contain the answer, reply exactly: NOT_FOUND\n"
    "- Keep the answer to one or two sentences."
)
PLAIN_SYSTEM = (
    "You answer questions about Arcaence Online, a subscription platform. "
    "Keep the answer to one or two sentences."
)

_reference = None


def reference():
    """Document statuses and the set of real (clause_id, doc_id) pairs."""
    global _reference
    if _reference is None:
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            status = dict(conn.execute("select doc_id, status from documents").fetchall())
            registry = set(conn.execute(
                "select clause_id, doc_id from clause_registry").fetchall())
        _reference = (status, registry)
    return _reference


def ask_model(system: str, user: str) -> str:
    reply = client.messages.create(
        model=MODEL, max_tokens=2000,
        system=system, messages=[{"role": "user", "content": user}],
    )
    # The reply can start with a thinking block; keep only the text blocks
    return "".join(b.text for b in reply.content if b.type == "text").strip()


def verify(answer: str, given: set[str]) -> list[str]:
    """Return the problems found in the answer's citations. Empty list = passes."""
    if answer.strip() == "NOT_FOUND":
        return []
    status, registry = reference()
    citations = CITE_RE.findall(answer)
    if not citations:
        return ["no citation"]
    problems = []
    for doc_id, clause_id in citations:
        label = f"{doc_id} {clause_id}".strip()
        if label not in given:
            problems.append(f"not among the sources it was given: [{label}]")
            continue
        if doc_id == "plans_fees":
            continue
        if doc_id not in status:
            problems.append(f"unknown document: [{label}]")
        elif status[doc_id] != "approved":
            problems.append(f"document is {status[doc_id]}, not citable: [{label}]")
        elif clause_id and (clause_id, doc_id) not in registry:
            problems.append(f"clause not in registry: [{label}]")
    return problems


def answer_question(question: str, mode: str) -> dict:
    """mode: plain, rag_off or rag_on."""
    if mode == "plain":
        return {"question": question, "mode": mode, "route": "none", "sources": [],
                "answer": ask_model(PLAIN_SYSTEM, question), "problems": None}

    path = route(question)
    labels, lines = set(), []
    if path == "sql":
        for plan, billing, currency, price, _ in price_lookup(question):
            lines.append(f"[plans_fees] {plan}, {billing}, {currency}: {price}")
        labels.add("plans_fees")
    else:
        rows = vector_search(question, 5, approved_only=(mode == "rag_on"))
        for doc_id, clause_id, _status, content, _score in rows:
            label = f"{doc_id} {clause_id}" if clause_id else doc_id
            labels.add(label)
            lines.append(f"[{label}] {content}")
    user = "Sources:\n" + "\n".join(lines) + f"\n\nQuestion: {question}"
    answer = ask_model(RAG_SYSTEM, user)
    return {"question": question, "mode": mode, "route": path, "sources": sorted(labels),
            "answer": answer, "problems": verify(answer, labels)}


QUESTIONS = [
    "How much does the Pro plan cost per month in euros?",
    "How long do I have to ask for a refund?",
    "Can I cancel my annual plan?",
]

if __name__ == "__main__":
    print("Verifier check on made-up answers:")
    for fake, given in [
        ("Refunds take 7 days [tos_v3 9.9].", {"tos_v3 2.2"}),
        ("Refunds take 14 days [tos_v2 2.2].", {"tos_v2 2.2"}),
        ("Refunds take 7 days [tos_v3 2.2].", {"tos_v3 2.2"}),
        ("Refunds take 7 days.", {"tos_v3 2.2"}),
    ]:
        print(f"  {fake:42} -> {verify(fake, given) or 'passes'}")

    for question in QUESTIONS:
        print(f"\n{question}")
        for mode in ("plain", "rag_off", "rag_on"):
            r = answer_question(question, mode)
            print(f"  [{mode}] {r['answer'][:150]}")
            if r["problems"] is not None:
                print(f"          check: {r['problems'] or 'passes'}")