"""Tracing: one Langfuse trace per case, metadata only, and it never breaks the service.

What a trace holds: case id, behavior, classifier label and confidence, route, citation labels
(like "tos_v3 3.2"), attempt counts, whether the review queue took the item, latency, error class
names. What it never holds: the customer's message, the answer text, the model's raw output,
verifier messages, keys or connection strings.

Four layers keep text out:
  1. record_case() builds the trace from named fields only, so there is nothing to leak by default.
  2. mask(): the SDK runs it over metadata values before export. Keys that hold text become
     "[not recorded]", and any string over 120 characters is cut to a marker.
  3. drop_io(): at export, every span loses its input and output fields, whatever code set them.
     mask() alone does not catch a short string passed as input, so this is the hard stop.
  4. test_tracing.py reads the exported spans and fails if the message or the answer appears.

Fail open: any tracing error is swallowed (the class name is logged) and the customer still gets the
answer. With no Langfuse keys in the environment, tracing is simply off.

The trace id is made from the case id, so the same case always maps to the same trace.
"""
import logging
import os

log = logging.getLogger("desk.tracing")

TEXT_KEYS = {"question", "answer", "message", "text", "content", "raw", "input", "output",
             "prompt", "reply", "problems", "attempt_log", "clarifying_question"}
MAX_STRING = 120
NOT_RECORDED = "[not recorded]"

_client = None
_tried = False


def mask(*, data, **_):
    """Applied by the SDK to input, output and metadata before anything is exported."""
    if isinstance(data, dict):
        return {k: (NOT_RECORDED if str(k).lower() in TEXT_KEYS else mask(data=v))
                for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [mask(data=v) for v in data]
    if isinstance(data, str) and len(data) > MAX_STRING:
        return NOT_RECORDED + " (long text)"
    return data


IO_ATTRIBUTES = ("langfuse.observation.input", "langfuse.observation.output",
                 "langfuse.trace.input", "langfuse.trace.output")


def drop_io(*, params):
    """Export-stage guard: delete input and output from every span about to be sent."""
    from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

    patches = {}
    for identifier, span in params.spans.items():
        found = tuple(k for k in IO_ATTRIBUTES if k in span.attributes)
        if found:
            patches[identifier] = OtelSpanPatch(delete_attributes=found)
    return MaskOtelSpansResult(span_patches=patches)


def make_client(**overrides):
    """A Langfuse client with both guards on. Tests pass span_exporter and dummy keys."""
    from langfuse import Langfuse
    return Langfuse(mask=mask, mask_otel_spans=drop_io, **overrides)


def get_client():
    """The shared client, or None when tracing is off. Built once; never raises."""
    global _client, _tried
    if _tried:
        return _client
    _tried = True
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return None
    try:
        _client = make_client(timeout=5)
    except Exception as exc:
        log.warning("tracing off: %s", type(exc).__name__)
        _client = None
    return _client


def use_client(client):
    """Tests and scripts set the client directly."""
    global _client, _tried
    _client, _tried = client, True


def _label(c) -> str:
    """A citation as the label people read: 'tos_v3 3.2'. The desk gives dicts, tests give strings."""
    if isinstance(c, dict):
        return f"{c.get('doc_id', '')} {c.get('clause_id', '')}".strip()
    return str(c)


def record_case(result: dict, latency_ms: int, client=None) -> str | None:
    """Write one trace for a finished case. Returns the trace id, or None. Never raises."""
    c = client or get_client()
    if c is None:
        return None
    try:
        from langfuse import propagate_attributes

        case_id = result["case_id"]
        trace_id = c.create_trace_id(seed=case_id)
        review = result.get("review", {})
        tri = result.get("triage", {})
        bil = result.get("billing", {})
        pri = result.get("privacy", {})
        summary = {
            "case_id": case_id,
            "behavior": result["behavior"],
            "label": result.get("label", ""),
            "classifier_confidence": result.get("classifier_confidence", ""),
            "classifier_note": result.get("classifier_note", ""),
            "route": result.get("route", "none"),
            "citations": [_label(x) for x in result.get("citations", [])],
            "attempts": result.get("attempts", 0),
            "refusal_reason": result.get("refusal_reason", ""),
            "handoff_needed": bool(result.get("handoff", {}).get("needed")),
            "review_queued": bool(review.get("queued")),
            "review_error": review.get("error", ""),
            "triage_ran": bool(tri.get("ran")),
            "triage_intent": tri.get("intent", ""),
            "triage_specialist": tri.get("specialist", ""),
            "triage_fallback": tri.get("fallback_reason", ""),
            "triage_dropped_facts": [str(x) for x in tri.get("dropped_facts", [])],
            "routing_queued": bool(tri.get("routing_queued")),
            "triage_error": tri.get("error", ""),
            "billing_ran": bool(bil.get("ran")),
            "billing_skipped": bil.get("skipped", ""),
            "billing_outcome": bil.get("outcome", ""),
            "billing_reason": bil.get("reason", ""),
            "billing_steps": int(bil.get("steps", 0)),
            "billing_would_refund": bool(bil.get("would_refund")),
            "billing_would_queue": bool(bil.get("would_queue")),
            "billing_error": bil.get("error", ""),
            "billing_proposal_queued": bool(bil.get("proposal_queued")),
            "billing_proposal_error": bil.get("proposal_error", ""),
            "privacy_ran": bool(pri.get("ran")),
            "privacy_skipped": pri.get("skipped", ""),
            "privacy_outcome": pri.get("outcome", ""),
            "privacy_reason": pri.get("reason", ""),
            "privacy_kind": pri.get("kind", ""),
            "privacy_steps": int(pri.get("steps", 0)),
            "privacy_would_open": bool(pri.get("would_open")),
            "privacy_would_cancel": bool(pri.get("would_cancel")),
            "privacy_error": pri.get("error", ""),
            "latency_ms": int(latency_ms),
        }
        with c.start_as_current_observation(
                trace_context={"trace_id": trace_id}, name="desk_message", as_type="span",
                metadata=summary):
            with propagate_attributes(session_id=case_id, trace_name="desk_message",
                                      tags=[result["behavior"]]):
                with c.start_as_current_observation(
                        name="classify", as_type="span",
                        metadata={"label": summary["label"],
                                  "confidence": summary["classifier_confidence"],
                                  "note": summary["classifier_note"]}):
                    pass
                if summary["triage_ran"]:
                    with c.start_as_current_observation(
                            name="triage", as_type="span",
                            metadata={"intent": summary["triage_intent"],
                                      "specialist": summary["triage_specialist"],
                                      "fallback": summary["triage_fallback"],
                                      "routing_queued": summary["routing_queued"]}):
                        pass
                if summary["billing_ran"]:
                    with c.start_as_current_observation(
                            name="billing_shadow", as_type="span",
                            metadata={"outcome": summary["billing_outcome"], "reason": summary["billing_reason"],
                                      "steps": summary["billing_steps"], "would_refund": summary["billing_would_refund"],
                                      "would_queue": summary["billing_would_queue"], "error": summary["billing_error"],
                                      "proposal_queued": summary["billing_proposal_queued"],
                                      "proposal_error": summary["billing_proposal_error"]}):
                        pass
                if summary["privacy_ran"]:
                    with c.start_as_current_observation(
                            name="privacy_shadow", as_type="span",
                            metadata={"outcome": summary["privacy_outcome"], "reason": summary["privacy_reason"],
                                      "kind": summary["privacy_kind"], "steps": summary["privacy_steps"],
                                      "would_open": summary["privacy_would_open"],
                                      "would_cancel": summary["privacy_would_cancel"], "error": summary["privacy_error"]}):
                        pass
                if summary["route"] != "none":
                    with c.start_as_current_observation(
                            name="answer", as_type="span",
                            metadata={"route": summary["route"], "attempts": summary["attempts"],
                                      "sources": [str(x) for x in result.get("sources", [])]}):
                        pass
        return trace_id
    except Exception as exc:
        log.warning("trace not recorded: %s", type(exc).__name__)
        return None


def flush():
    """Send what is waiting. Called at shutdown; never raises."""
    try:
        if _client is not None:
            _client.flush()
    except Exception as exc:
        log.warning("trace flush failed: %s", type(exc).__name__)
