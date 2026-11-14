import json
import os
import re

import psycopg
from anthropic import Anthropic
from dotenv import load_dotenv

from retrieval import price_lookup, route, vector_search

load_dotenv()

MODEL = "claude-haiku-5-5"
MAX_RETRIES = 2
client = Anthropic()

# [tos_v3 2.2]  [schedule_ab_v3 B.2]  [plans_fees]
CITE_RE = re.compile(r"\[(\w+)(?:\s+([\w.]+))?\]")

RAG_SYSTEM = (
    "You answer questions about Arcaence Online, a fictional subscription platform.\n"
    "Rules:\n"
    "- Answer only from the sources below. Do not use outside knowledge.\n"
    "- Each source starts with a label in square brackets, for example [tos_v3 2.2] "
    "or [plans_fees]. List every source you used in citations: doc_id is the first "
    "part of the label, clause_id is the second part (empty string for plans_fees).\n"
    "- Write the answer text without square brackets.\n"
    "- If the sources do not contain the answer, set refused to true, leave answer "
    "and citations empty, and give a short refusal_reason.\n"
    "- Keep the answer to one or two sentences."
)
PLAIN_SYSTEM = (
    "You answer questions about Arcaence Online, a subscription platform. "
    "Keep the answer to one or two sentences."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "clause_id": {"type": "string"},
                },
                "required": ["doc_id", "clause_id"],
                "additionalProperties": False,
            },
        },
        "refused": {"type": "boolean"},
        "refusal_reason": {"type": "string"},
    },
    "required": ["answer", "citations", "refused", "refusal_reason"],
    "additionalProperties": False,
}

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


def ask_structured(system: str, messages: list) -> tuple[dict | None, str]:
    """One schema-constrained call. Returns (parsed result or None, raw text)."""
    reply = client.messages.create(
        model=MODEL, max_tokens=2000, system=system, messages=messages,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    raw = "".join(b.text for b in reply.content if b.type == "text").strip()
    try:
        return json.loads(raw), raw
    except ValueError:
        return None, raw


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


def label_of(citation: dict) -> str:
    doc_id = citation["doc_id"].strip()
    clause_id = citation["clause_id"].strip()
    return f"{doc_id} {clause_id}" if clause_id else doc_id


def check(result: dict, given: set[str]) -> list[str]:
    """Problems with a structured answer. Empty list = acceptable."""
    if result["refused"]:
        return []  # a refusal makes no claims, so there is nothing to verify
    problems = []
    if not result["answer"].strip():
        problems.append("answer is empty")
    if not result["citations"]:
        problems.append("answer has no citations")
        return problems
    text = " ".join(f"[{label_of(c)}]" for c in result["citations"])
    problems += list(verify(text, given) or [])
    return problems


def answer_with_retry(system: str, user: str, labels: set[str]) -> dict:
    """Ask, verify, and retry with the verifier's reasons. Never returns an unverified answer."""
    messages = [{"role": "user", "content": user}]
    log = []
    for attempt in range(1, MAX_RETRIES + 2):
        result, raw = ask_structured(system, messages)
        problems = ["reply was not valid JSON"] if result is None else check(result, labels)
        log.append({"attempt": attempt, "raw": raw, "problems": problems})
        if not problems:
            return {"result": result, "attempts": attempt, "log": log}
        feedback = ("Your answer was rejected by the verifier:\n- " + "\n- ".join(problems)
                    + "\nCite only the sources listed above, exactly by label, "
                    "or refuse if they do not contain the answer.")
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": feedback}]
    fallback = {"answer": "", "citations": [], "refused": True,
                "refusal_reason": "verification_failed"}
    return {"result": fallback, "attempts": len(log), "log": log}


def answer_question(question: str, mode: str) -> dict:
    """mode: plain, rag_off or rag_on."""
    if mode == "plain":
        return {"question": question, "mode": mode, "route": "none", "sources": [],
                "answer": ask_model(PLAIN_SYSTEM, question), "problems": None}

    path = route(question)
    labels, lines = set(), []
    if path == "sql":
        for plan, billing, currency, price, note in price_lookup(question):
            value = price if price is not None else note
            lines.append(f"[plans_fees] {plan}, {billing}, {currency}: {value}")
        labels.add("plans_fees")
    # Policy questions often contain price words, so the vector index is always searched too.
    rows = vector_search(question, 8, approved_only=(mode == "rag_on"))
    for doc_id, clause_id, _status, content, _score in rows:
        label = f"{doc_id} {clause_id}" if clause_id else doc_id
        labels.add(label)
        lines.append(f"[{label}] {content}")
    user = "Sources:\n" + "\n".join(lines) + f"\n\nQuestion: {question}"

    out = answer_with_retry(RAG_SYSTEM, user, labels)
    result = out["result"]
    if result["refused"]:
        answer = "NOT_FOUND"
    else:
        cites = " ".join(f"[{label_of(c)}]" for c in result["citations"])
        answer = f"{result['answer'].strip()} {cites}"
    return {"question": question, "mode": mode, "route": path, "sources": sorted(labels),
            "answer": answer, "problems": [], "refused": result["refused"],
            "refusal_reason": result["refusal_reason"], "citations": result["citations"],
            "attempts": out["attempts"], "attempt_log": out["log"]}


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
                print(f"          attempts: {r.get('attempts')}  refused: {r.get('refused')}")