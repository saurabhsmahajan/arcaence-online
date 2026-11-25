# G3 evidence: eval in CI, review queue and service

Run: 25 Nov 2026, 23:23 IST · code commit: 8c46eac · result: **G3 met**

Gate G3 is "RAG eval in CI and review queue". It is met when five things hold at once, on the code that is on `main`:

1. The evaluation gate runs in CI on every push and passes, with the secret-free tests running beside it.
2. The review queue holds proposed actions as well as answers, and the database enforces its states.
3. Every reply carries a case ID that the server made.
4. The desk is a service with a key, rate limit, daily cap, concurrency limit and safe errors, and it runs as a container with no secret inside.
5. Every case leaves one trace keyed by its case ID, and no message text is in it.

## The five conditions

| # | Condition | Evidence | Result |
| --- | --- | --- | --- |
| 1 | Eval gate in CI | `eval-gate` runs for 0b3fce5, f1403da and 8c46eac all green. The offline job runs six test files with no secrets and no database (16, 26, 13, 12, 26 and 38 checks). The gate job checks the login is the read-only `ci_eval` one, then runs the desk gate against the saved baseline (unsupported-claim rate 0.0%). No pull-request trigger, so secrets are never reachable from a fork. | Met |
| 2 | Review queue | `test_review_queue.py` 27 checks and `test_review.py` 7 checks. Answer items go open to resolved only, action items open to approved or rejected only, a decision needs `decided_by`, final states are final, nothing is deleted. Approving records a decision and runs nothing. Three real hostile cases are open in the table. | Met |
| 3 | Case ID | `test_case.py` 13 checks. Format `case_YYYYMMDD_` plus 12 hex characters, made on the server, never taken from the caller. Every live reply below carries one. | Met |
| 4 | Service and container | `test_service.py` 38 checks. Live, in the container: a request with no key got 401, a valid request got a grounded answer with citations, the container reported `healthy`, and no `.env` file was in the image (count 0). It runs as a non-root user and takes its secrets at start. | Met |
| 5 | Tracing | `test_tracing.py` 26 checks, including a probe that tries to send short text as input and output and must not see it at export. Live: three traces in Langfuse, Input and Output empty on all three. | Met |

## The live run

The rebuilt image ran with the `desk_service` login, the Anthropic key, a throwaway service key and the Langfuse keys, all passed at start.

| Time (IST) | Case | Message type | Behavior | Queued | Trace |
| --- | --- | --- | --- | --- | --- |
| 23:23:19 | case_20261125_9ab231c4e766 | refund and cancellation question | answer, cited tos_v3 3.2 and 3.3 | no (not needed) | present, spans classify and answer |
| 23:23:22 | case_20261125_f31e57a91bac | angry, threatens bank and lawyer | escalate, `needs_person` true | yes, reason `hostile`, status `open` | present, span classify only (no retrieval ran) |
| 23:25:00 | case_20261125_87e2d8a718ea | account closure question | answer, cited tos_v3 6.3, 5.3 and 5.2 | no (not needed) | present, although the container was stopped right after the reply |

The third row is the shutdown proof. The SDK sends traces in batches every few seconds, so a trace from a request followed at once by a stop exists only if the service flushes when it stops. The log showed a clean shutdown with no flush warning, and the trace was there.

## Known limits

These are recorded, not hidden.

| Limit | Why it is acceptable now | Where it is handled |
| --- | --- | --- |
| Rate limit and daily cap live in one process's memory | One instance; a restart resets the day's count. Several instances would need a shared store. | Phase 6 (28 Nov) |
| The daily cap counts requests, not tokens | Each request makes at most four model calls, so spend is bounded by 500 requests times four calls. | Token counts in traces, Phase 6 |
| Span durations in traces are near zero | Spans are written after the reply is built. The real total is in the `latency_ms` field. | Stage timing, Phase 6 |
| First request took about 10 seconds | Not yet broken down by stage. | Stage timing, Phase 6 |
| Proposed actions are only queued | No agent consumes them yet. | Desk agents, 25 to 27 Nov |
| Third-party GitHub Actions are tagged, not pinned to commit hashes | The tj-actions case (CVE-2025-30066) shows why pinning matters. | Housekeeping |
| Two database passwords were shared in chat and are not yet rotated | `desk_service` and the owner login from 20 Nov. | Housekeeping |

Model answers are not identical between runs (the second run of the same question cited an extra clause). That is the non-determinism measured on Day 12, and the gate scores rules, not exact wording.
