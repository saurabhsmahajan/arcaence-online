"""Smoke test: one hostile and one normal message through the handler. Run from the rag folder.
The hostile message adds a REAL item to the review queue (synthetic data) and calls the API."""
from handler import handle_message

for m in ["My lawyer will be in touch about the refund you refused me.",
          "How long do I have to ask for a refund on a one-off purchase?"]:
    r = handle_message(m)
    print(f"\n> {m}\n  case={r['case_id']} label={r['label']} behavior={r['behavior']}")
    print(f"  review={r['review']}")
    print(f"  {r['answer'][:120]}")
