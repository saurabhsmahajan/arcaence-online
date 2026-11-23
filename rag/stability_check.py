"""How stable is the classifier on borderline messages? Run from the rag folder:
  uv run python stability_check.py
Asks each message N times at the default temperature and at temperature 0, and prints the
label counts. Calls the API directly and prints errors (the classifier's own fallback would
hide them)."""
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from classifier import MODEL, SCHEMA, SYSTEM, client

N = 10
MESSAGES = {
    "Q08": "When does a downgrade take effect, and do I get money back?",
    "Q35": "Is the Legacy Pro plan still available, and what does it cost?",
    "Q42": "Can I cancel?",
    "Q49": "Can I get my money back?",
    "Q60": "This is the third time I ask. Why does nobody answer me?",
    "Q66": "How do I report an accessibility barrier, and does the site have a screen reader mode?",
    "Q67": "Do you keep my payment records after I close my account, and are my backups deleted too?",
    "Q61": "Can I get a refund within a week, and do you give student discounts?",
}


def ask(text, temperature):
    kwargs = {} if temperature is None else {"temperature": temperature}
    try:
        reply = client.messages.create(
            model=MODEL, max_tokens=500, system=SYSTEM,
            messages=[{"role": "user", "content": f"Message: {text}"}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}}, **kwargs)
        raw = "".join(b.text for b in reply.content if b.type == "text").strip()
        return json.loads(raw)["label"]
    except Exception as exc:
        return f"ERROR {type(exc).__name__}: {str(exc)[:80]}"


with ThreadPoolExecutor(8) as pool:
    for temp in (None, 0):
        print(f"\n=== temperature {'default' if temp is None else temp}, {N} samples each ===")
        for qid, text in MESSAGES.items():
            labels = list(pool.map(lambda _: ask(text, temp), range(N)))
            print(f"{qid}  {dict(Counter(labels))}")
