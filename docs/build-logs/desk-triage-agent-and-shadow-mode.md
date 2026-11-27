# Desk triage agent: typed handoff, shadow mode and honest evaluation (25 Nov plan row, finished by 27 Nov 2026)

Status: the 25 Nov row is done. The triage agent decides who should handle a message, runs in shadow mode, and is covered by a golden set, an eval runner, tests and traces. It was planned for 25 Nov and finished by 27 Nov. The 26 Nov row, the billing agent, is next. No new gate was due; G3 stays met.

This is the log for the desk triage agent. The previous log is [rag-phase-4-5-service-and-tracing.md](rag-phase-4-5-service-and-tracing.md). The architecture is on the [v0.14 page](../architecture/v0.14-triage-agent-typed-handoff-and-shadow-mode.md), and the study notes are [Day 14](../notes/day-14-triage-agent-typed-handoffs-shadow-mode-honest-eval.md).

## 25 to 27 Nov: the triage agent, the typed handoff and shadow mode

A triage agent reads a customer message and returns a typed handoff: an intent, a confidence and four facts. It decides who handles the message, never what to do. It has no tools and sees no customer data. Code checks the handoff before anything uses it. In shadow mode the handler queues one routing note and the customer's reply does not change. Code commits: `6a139bd`, `96cf8d4`, `3e56ee0`. CI was green on `96cf8d4` (offline job 12 s, gate job 6 m 24 s).

| Area | Finding | How we handle it | Check |
| --- | --- | --- | --- |
| Handoff contract | A schema makes the shape likely, not safe. | `triage_logic.py` holds the intents, the specialist map and the four fact keys. `clean_handoff` returns the cleaned handoff, the dropped facts and the fatal problems: a broken shape, intent or confidence is fatal, a broken single fact is dropped and the route is kept. | `test_triage_logic.py` (35 checks). |
| Newline trap in a pattern | A pattern ending in `$` accepted `ord_1042` followed by a newline. | Patterns use `fullmatch` with no anchors, and ASCII classes only (`ord_[0-9]{4}`, `[0-9]{1,9}(\.[0-9]{1,2})?`). | A check feeds the newline case and must reject it. |
| Facts on a policy question | The first dev run failed the gate: 22 of 25 right, rows T25, T29 and T35 wrong. | A code rule sets facts to null when there is no specialist. The prompt got a rule that how, what and whether questions are policy questions even when they mention an action, and a rule that maps currency words and symbols to EUR, USD or INR. | Dev run twice more: 25 of 25 both times, gate passed. |
| Bad fact discarded the whole handoff | On the first holdout, row T34 lost its route because one invalid fact made the code discard the handoff, against the golden label. | `clean_handoff` now drops the bad fact to null and keeps the route. | `test_triage_logic.py`, and the holdout row. |
| Lucky fallbacks counted as correct | A fallback gives `policy_question`, so a row whose true intent was policy_question scored correct by luck. | The scorer never counts a fallback as a correct intent, and flags it as `fallback`. The gate runs on single-request rows: zero false routes, zero invented facts, intent accuracy of at least 90 percent. Multi-request rows are reported apart. | `test_triage_scoring.py` (17 checks). |
| Fallbacks with `JSONDecodeError` | Three holdout rows came back as fallbacks with no clue why. | `probe_triage.py` re-ran them and recorded the stop reason and length: `stop=max_tokens, len=0`. Thinking tokens had used the 300-token budget. `max_tokens` went to 2000. The fallback reason now holds the error class plus `(stop=..., len=...)`, never the text. | Probe before and after the fix; `test_triage.py` (21 checks). |
| An intent flip | A question about a screen reader was read as an `account` request. | The `account` definition in the prompt was tightened. | Re-run of the row. |
| Holdout burned | Fixes were made against holdout v1 (8 of 11), so it could no longer be a fair test. | It became a second dev set. A fresh holdout2 (16 rows, 15 scored) was written before its run and run once: 15 of 15. | `eval/golden_set_triage.csv`: 54 rows (26 dev, 12 holdout, 16 holdout2), rules in `golden_set_triage_rules.md`. |
| A wrong test of mine | One test counted a fallback reason length as 14 when it was 15. | The test was corrected. The code was right. | `test_triage.py`. |
| Shadow mode | Wiring triage into `desk_answer()` would put it in the path of every reply and the v0.12 desk tests. | Triage runs in the handler, after the review block and before tracing, only for normal or multi cases. It queues a routing note through `enqueue_action` (tool `route_case`) when there is no fallback and a specialist exists. Any error is recorded by class and the reply is unchanged. | `test_handler_triage.py` (21 checks). |
| Routing note summary | A model-written summary would put model text in front of the reviewer. | The summary is built by code from fixed words: "Route to the {specialist} agent: the message looks like a {intent} request." | `test_handler_triage.py`. |
| Tracing | Triage had to be visible in traces without the message text. | The root trace gets `triage_ran`, `triage_intent`, `triage_specialist`, `triage_fallback`, `triage_dropped_facts`, `routing_queued` and `triage_error`, plus a child span `triage` when it ran. The queue item id and the text stay out. | `test_tracing.py` (34 checks). |
| Reading routing notes | Notes sat in the queue with no way to list them. | `scripts/show_routing_notes.py` lists `proposed_action` items with tool, args and summary, read-only. | Added in `3e56ee0`; run against the live queue. |
| CI | The new tests had to run without a key. | The offline job runs ten test files with no secrets and no database (four triage tests added). The triage eval needs an API key, so it is not in CI. | Green run after `96cf8d4`. |
| Live check | The unit tests use fakes, so the real service had to be seen working. | The container was built and started. Before `docker run` the checks I had asked for came back with all five True. A request produced a routing note in the queue, and two Langfuse traces showed triage metadata with no message text. | Output of the viewer script and the trace pages. |

Decisions (proposed in the notes and recorded as rows 063 to 069 in [decisions.md](../architecture/decisions.md)): triage decides who and never what, with no tools and no data (ADR-063); the message is data, not instructions (ADR-064); the typed handoff is checked in code (ADR-065); a safe fallback with a diagnostic reason (ADR-066); shadow mode in the handler (ADR-067); scoring by cost of error with a burned holdout replaced (ADR-068); the routing note goes through `enqueue_action` with a fixed-word summary (ADR-069).

Result: met. Triage scored 25 of 25 on the dev set (twice) and 15 of 15 on a fresh holdout run once. The service queued a routing note and left the reply unchanged, and the traces carry triage metadata and no text.

Known limits:

- A routed request still gets a refusal and `needs_person` stays false, because no specialist agent exists yet.
- One intent per message. A second request in the same message is lost, and multi-request rows are reported apart.
- Holdout2 has 15 scored rows and the model is sampled, so 15 of 15 is a good sign, not proof. Holdout v1 is burned.
- The triage eval is not in CI because it needs a key.
- Confidence is recorded but nothing reads it.
- Routing notes accumulate. Nothing consumes them and there is no screen for them.
- Span durations are near zero, and the rate and concurrency limits are per process.
- The `desk_service` password and the 20 Nov owner password are due for rotation. Third-party GitHub Actions are not yet pinned to commit hashes.
- The untracked `eval/results` files stay uncommitted. The evidence note for the live run is not written yet.
