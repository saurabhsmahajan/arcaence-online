"""Pure logic for the desk pipeline. No API, database or network, so it tests offline.

The desk pipeline classifies a message, then takes one of four paths:
  normal   -> the existing rag_on answer path (unchanged)
  vague    -> one clarifying question
  hostile  -> a fixed reply written here, never by a model, plus a handoff flag
  multi    -> an answer split into parts; the model only decides covered or not covered,
              and the wording for an uncovered part is fixed here
"""

HOSTILE_REPLY = (
    "I'm sorry this has been frustrating. I can't decide refunds, compensation or "
    "legal questions, and I don't want to say something I can't confirm. "
    "This needs a person, so I'm marking it for review by our team."
)

FALLBACK_CLARIFY = (
    "Could you tell me a little more about what you need, for example a refund, "
    "a cancellation, a plan change, a payment or your data?"
)

NOT_COVERED = "I can't find the answer to this part in the official documents, so I won't guess: {part}"
HELP_LINE = "The Help Centre can help with the part I could not answer."

PARTS_SCHEMA = {
    "type": "object",
    "properties": {
        "parts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "part": {"type": "string"},
                    "covered": {"type": "boolean"},
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
                },
                "required": ["part", "covered", "answer", "citations"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["parts"],
    "additionalProperties": False,
}

PARTS_SYSTEM = (
    "You answer questions about Arcaence Online, a fictional subscription platform.\n"
    "The message contains more than one question. Split it into its separate questions "
    "and treat each one as a part.\n"
    "Rules:\n"
    "- Answer only from the sources below. Do not use outside knowledge.\n"
    "- Each source starts with a label in square brackets, for example [tos_v3 2.2] "
    "or [plans_fees]. doc_id is the first part of the label, clause_id is the second "
    "part (empty string for plans_fees).\n"
    "- For each part set covered to true only if the sources contain what is needed to "
    "answer that part. Then write one sentence in answer, without square brackets, and "
    "list every source you used in citations.\n"
    "- If the sources lead to a no (for example a deadline has passed), that is an "
    "answer: covered is true.\n"
    "- If the sources do not contain what that part needs, set covered to false and "
    "leave answer empty and citations empty. Never guess a covered part."
)


def flat_citations(result: dict) -> list[dict]:
    return [c for p in result.get("parts", []) if p["covered"] for c in p["citations"]]


def parts_problems(result: dict, check_fn, labels: set[str]) -> list[str]:
    """Problems with a parts answer. Empty list = acceptable.

    check_fn(result_like, labels) is answer.check: it verifies citations against the
    sources the model was given and the clause registry.
    """
    parts = result.get("parts", [])
    if not parts:
        return ["no parts returned"]
    problems = []
    for i, p in enumerate(parts, 1):
        if p["covered"]:
            if not p["answer"].strip():
                problems.append(f"part {i} is covered but has no answer")
            if not p["citations"]:
                problems.append(f"part {i} is covered but has no citations")
        elif p["answer"].strip() or p["citations"]:
            problems.append(f"part {i} is not covered, so answer and citations must be empty")
    flat = flat_citations(result)
    if flat:
        problems += check_fn({"refused": False, "answer": "x", "citations": flat}, labels)
    return problems


def compose_parts(result: dict, label_of) -> tuple[str, str]:
    """Final text and behaviour (answer, partial or refuse) for a verified parts result."""
    pieces, covered, missing = [], 0, 0
    for p in result["parts"]:
        if p["covered"]:
            covered += 1
            cites = " ".join(f"[{label_of(c)}]" for c in p["citations"])
            pieces.append(f"{p['answer'].strip()} {cites}")
        else:
            missing += 1
            pieces.append(NOT_COVERED.format(part=p["part"].strip()))
    if missing:
        pieces.append(HELP_LINE)
    behavior = "answer" if not missing else ("refuse" if not covered else "partial")
    return " ".join(pieces), behavior
