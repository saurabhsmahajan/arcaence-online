"""Smoke test: one message of each kind through the desk pipeline. Run from the rag folder."""
from desk import desk_answer

MESSAGES = [
    "How long do I have to ask for a refund on a one-off purchase?",
    "Can I cancel?",
    "My lawyer will be in touch about the refund you refused me.",
    "How long do you keep my invoices, and will I get compensation for the downtime?",
    "Do upgrades start immediately, and do you have a family plan?",
]
for m in MESSAGES:
    r = desk_answer(m)
    print(f"\n> {m}\n  case={r['case_id']} label={r['label']} behavior={r['behavior']} handoff={r['handoff']['needed']}")
    print(f"  {r['answer']}")
