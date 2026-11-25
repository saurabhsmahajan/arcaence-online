"""Live check: one real question through the desk, one trace sent to Langfuse.

Run from the rag folder:  uv run python try_tracing.py
Needs DATABASE_URL (desk_service), ANTHROPIC_API_KEY and the two LANGFUSE_* keys in this window.
A normal question is used on purpose: it is answered, not queued, so the review queue stays clean.
"""
import tracing
from handler import handle_message

QUESTION = "How long do I have to cancel my subscription and get a refund?"

client = tracing.get_client()
if client is None:
    raise SystemExit("Tracing is off: set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in this window.")
print("keys accepted by Langfuse:", client.auth_check())

result = handle_message(QUESTION)
print("case     :", result["case_id"])
print("behavior :", result["behavior"], "| citations:", result["citations"])

trace_id = client.create_trace_id(seed=result["case_id"])
tracing.flush()
print("trace url:", client.get_trace_url(trace_id=trace_id))
print("\nOpen the link. Search the case id in Tracing if the link does not open.")
