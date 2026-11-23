"""Desk pipeline: classify the message, then take the path that fits.

normal  -> answer_question(question, "rag_on"), exactly as before
vague   -> one clarifying question, no retrieval
hostile -> fixed reply (desk_logic.HOSTILE_REPLY) and a handoff flag, no model wording
multi   -> retrieval, then a parts answer: each part is covered or not covered

answer.py is not changed: the measured rag_on path stays exactly what the older results
were scored against. The handoff flag is only a flag for now; the review queue that
consumes it is built in Phase 4.
"""
import json

from answer import MAX_RETRIES, MODEL, answer_question, check, client, label_of
from classifier import classify
from desk_logic import (FALLBACK_CLARIFY, HOSTILE_REPLY, PARTS_SCHEMA, PARTS_SYSTEM,
                        compose_parts, parts_problems)
from retrieval import expand_references, price_lookup, route, vector_search


def gather(question: str) -> tuple[str, set[str], list[str]]:
    """Same source gathering as answer_question in rag_on mode."""
    path = route(question)
    labels, lines = set(), []
    if path == "sql":
        for plan, billing, currency, price, note in price_lookup(question):
            value = price if price is not None else note
            lines.append(f"[plans_fees] {plan}, {billing}, {currency}: {value}")
        labels.add("plans_fees")
    rows = expand_references(vector_search(question, 8, approved_only=True), approved_only=True)
    for doc_id, clause_id, _status, content, _score in rows:
        label = f"{doc_id} {clause_id}" if clause_id else doc_id
        labels.add(label)
        lines.append(f"[{label}] {content}")
    return path, labels, lines


def ask_parts(messages: list) -> tuple[dict | None, str]:
    reply = client.messages.create(
        model=MODEL, max_tokens=2000, system=PARTS_SYSTEM, messages=messages,
        output_config={"format": {"type": "json_schema", "schema": PARTS_SCHEMA}},
    )
    raw = "".join(b.text for b in reply.content if b.type == "text").strip()
    try:
        return json.loads(raw), raw
    except ValueError:
        return None, raw


def parts_with_retry(user: str, labels: set[str]) -> dict:
    """Ask, verify, retry with the verifier's reasons. Never returns an unverified answer."""
    messages = [{"role": "user", "content": user}]
    log = []
    for attempt in range(1, MAX_RETRIES + 2):
        result, raw = ask_parts(messages)
        problems = (["reply was not valid JSON"] if result is None
                    else parts_problems(result, check, labels))
        log.append({"attempt": attempt, "raw": raw, "problems": problems})
        if not problems:
            return {"result": result, "attempts": attempt, "log": log}
        feedback = ("Your answer was rejected by the verifier:\n- " + "\n- ".join(problems)
                    + "\nCite only the sources listed above, exactly by label. "
                    "Mark a part as not covered if the sources do not contain its answer.")
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": feedback}]
    return {"result": None, "attempts": len(log), "log": log}


def desk_answer(question: str) -> dict:
    cls = classify(question)
    label = cls["label"]
    out = {
        "question": question, "mode": "desk", "label": label,
        "classifier_confidence": cls["confidence"], "classifier_note": cls["fallback_reason"],
        "behavior": "answer", "answer": "", "citations": [], "sources": [], "route": "none",
        "refused": False, "refusal_reason": "", "attempts": 0, "problems": [],
        "handoff": {"needed": False, "reason": ""},
    }

    if label == "vague":
        out.update(behavior="clarify",
                   answer=cls["clarifying_question"].strip() or FALLBACK_CLARIFY)
    elif label == "hostile":
        out.update(behavior="escalate", answer=HOSTILE_REPLY,
                   handoff={"needed": True, "reason": "hostile"})
    elif label == "multi":
        path, labels, lines = gather(question)
        user = "Sources:\n" + "\n".join(lines) + f"\n\nQuestion: {question}"
        res = parts_with_retry(user, labels)
        out.update(route=path, sources=sorted(labels), attempts=res["attempts"],
                   attempt_log=res["log"])
        if res["result"] is None:
            out.update(behavior="refuse", answer="NOT_FOUND", refused=True,
                       refusal_reason="verification_failed",
                       handoff={"needed": True, "reason": "verification_failed"})
        else:
            text, behavior = compose_parts(res["result"], label_of)
            flat = [c for p in res["result"]["parts"] if p["covered"] for c in p["citations"]]
            out.update(behavior=behavior, answer=text, citations=flat,
                       refused=(behavior == "refuse"),
                       refusal_reason="no_part_covered" if behavior == "refuse" else "")
    else:
        res = answer_question(question, "rag_on")
        out.update(behavior="refuse" if res["refused"] else "answer",
                   route=res["route"], sources=res["sources"], answer=res["answer"],
                   citations=res["citations"], refused=res["refused"],
                   refusal_reason=res["refusal_reason"], attempts=res["attempts"],
                   attempt_log=res["attempt_log"])
    return out
