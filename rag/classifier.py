"""Question classifier: labels a customer message before retrieval.

Labels
  normal   a clear question or request about one topic (the default path)
  vague    too little detail to pick a clause; one clarifying question is needed
  hostile  angry, or threatens a lawyer, regulator, bank dispute or publicity
  multi    two or more separate questions in one message

Safe fallback: on an API error, an unparsable reply or an invalid label, the label is
"normal", so the existing answer path runs exactly as before.
"""
import json

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-haiku-5-5"
LABELS = ["normal", "vague", "hostile", "multi"]
client = Anthropic()

SYSTEM = """You label one message sent to the support desk of Arcaence Online, a fictional
subscription platform. Choose exactly one label.

normal  - a clear question or request about ONE topic, even if it is short or unusual. It may
          include dates or amounts. Extra detail on the same topic is still one question:
          "How does X work, and how is it rounded?" is normal.
          Example: "Does the Team plan include 5 seats?"
vague   - the message does not say what was bought or what happened, so no single rule can be
          picked; one follow-up question would fix that. A clear wish with no situation
          ("I want out") is vague. Example: "It is not working."
hostile - the sender is angry or makes a threat (a lawyer, a court, a regulator, a bank
          dispute, going public, a demand for a manager), OR demands a written promise,
          guarantee, admission of fault or compensation that a support desk cannot grant,
          even in polite words. A calm question that only mentions a bank dispute or a legal
          topic is NOT hostile.
multi   - two or more separate questions about DIFFERENT topics.
          Example: "How do I reset my password, and what are your opening hours?"

Priority when several apply: hostile, then multi, then vague, then normal.
Set confidence to "low" when you are unsure.
Fill clarifying_question only for vague (one short question), otherwise use an empty string."""

SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": LABELS},
        "confidence": {"type": "string", "enum": ["high", "low"]},
        "clarifying_question": {"type": "string"},
    },
    "required": ["label", "confidence", "clarifying_question"],
    "additionalProperties": False,
}


def classify(question: str) -> dict:
    """Returns {label, confidence, clarifying_question, fallback, fallback_reason}. Never raises.

    Only an API error or an invalid label falls back to "normal" (the existing path).
    Confidence is recorded but never discards a label: in the first two runs the model's
    low-confidence labels were mostly right, and wrongly answering an unclear or angry
    message costs more than one extra clarifying question or one needless human review.
    """
    safe = {"label": "normal", "confidence": "low", "clarifying_question": "",
            "fallback": True, "fallback_reason": "error"}
    try:
        reply = client.messages.create(
            model=MODEL, max_tokens=500, system=SYSTEM,
            messages=[{"role": "user", "content": f"Message: {question}"}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        )
        raw = "".join(b.text for b in reply.content if b.type == "text").strip()
        out = json.loads(raw)
    except Exception as exc:
        return {**safe, "fallback_reason": f"error: {type(exc).__name__}"}
    if out.get("label") not in LABELS:
        return {**safe, "fallback_reason": "bad label"}
    out["fallback"] = False
    out["fallback_reason"] = "low confidence" if out.get("confidence") != "high" else ""
    return out
