# RAG Phases 4 and 5: case ID, review queue, desk service, container and tracing (24 to 25 Nov 2026)

Status: the 24 Nov row is done, and gate G3 is met (evidence: [g3-eval-ci-review-queue-and-service-2026-11-25.md](../evidence/g3-eval-ci-review-queue-and-service-2026-11-25.md)). The work was planned for 24 Nov and finished late on 25 Nov. The 25 Nov row, the desk triage agent, is next.

This is the log for RAG Phases 4 and 5. The Phase 3 log is [rag-phase-3-evals-and-desk.md](rag-phase-3-evals-and-desk.md). The architecture is on the [v0.13 page](../architecture/v0.13-case-id-review-queue-desk-service-container-and-tracing.md).

## 24 to 25 Nov: case ID, review queue, desk service, container and tracing

Every reply now carries a case ID made by the server. A hostile or unverified case writes a row to a review queue whose states the database enforces. The desk runs as an HTTP service with a key per client, a rate limit, a daily cap and a concurrency limit, inside a container with no secret in it. Each case leaves one Langfuse trace that holds metadata only. Code commits: `dff5642`, `ab01bc9`, `165974c`, `797fee2`, `f6c6741`, `0b3fce5`, `61a93e8`, `f1403da`, `8c46eac`.

| Area | Finding | How we handle it | Check |
| --- | --- | --- | --- |
| Identity of a case | A reply, a queue item and a trace had nothing joining them. | `case.py` makes `case_YYYYMMDD_` plus 12 lowercase hex characters on the server, and the trace ID is computed from it. A caller can never supply one. | `test_case.py` (13 checks). |
| Review queue | The hostile reply promised a review, but the handoff flag had no reader. | Migration 015 adds `ops.review_items`: two kinds (answer, proposed_action), four statuses, and a trigger that allows only open to resolved for answers and open to approved or rejected for actions. A decision needs `decided_by` and `decided_at`; no row is deleted. Approval only records a decision. | `test_review_queue.py` (27 checks) and `test_review.py` (7 checks). |
| Service login | The service would have run as the owner, which bypasses row-level security. | Migration 016 adds `desk_service`: select on four knowledge tables, execute `search_policy`, select and insert on `ops.review_items`, a 10 second statement timeout. | `check_desk_role.py`: 15 probes, each rolled back, ending `DESK ROLE CHECK: PASS`. |
| Promise that may be false | If the queue write fails, the escalate reply still says a person will review the message. | The handler replaces the reply with a fixed text that promises nothing, records `queued: false`, and keeps only the error class name. Side effects stay out of `desk_answer()`. | `test_handler.py` (12 checks), including a failing queue write. |
| Service controls | A paid model behind an open endpoint can be drained without the service ever going down. | `service.py`: input of 1 to 2,000 characters, an API key per client compared in constant time, a token bucket of 10 a minute with a burst of 5, a daily cap of 500, 4 at once, generic errors, no `/docs`. | `test_service.py` (38 checks). Live: a request with no key got 401. |
| Order of the checks | The framework checks the body before the handler runs, so the input check comes before the key check. | Kept and documented: a caller with no key and a malformed body gets a 422, not a 401. Nothing is leaked. | Noted in ADR-059 and on the v0.13 page. |
| Port already in use | The container would not start: port 8000 was held by a leftover Python process from an earlier run. | The process was found with `Get-NetTCPConnection`, stopped, and the container started. The port is published to 127.0.0.1 only. | `docker ps` showed the container healthy and `/healthz` returned ok. |
| Secrets in the image | A copied `.env` would travel with every copy of the image. | `.dockerignore` excludes `.env*`, tests and scripts. Settings arrive with `docker run -e NAME`. The model is baked in; the user is non-root (uid 10001); a healthcheck watches `/healthz`. | A check showed 0 `.env` files in the image and that the imports work. |
| Masking gap | Short text placed in a span's input or output was not masked, because the mask cut only long strings and masked named text keys. | An export guard (`drop_io`, through `mask_otel_spans`) deletes the input and output attributes before export. A probe test sends short text as input and output and must not see it. | `test_tracing.py` (26 checks). Live: Input and Output empty on all three traces. |
| Citations stored as dict strings | The first live trace showed citations as dict text, not labels. | `_label` turns a dict citation into `doc_id clause_id`. A test now uses dict citations. | `test_tracing.py`. |
| Tests sending real traces | The handler tests could have sent real traces to Langfuse. | Two lines in `test_handler.py` call `tracing.use_client(None)` so tests never send anything. | `test_handler.py` runs with no keys. |
| Traces lost at shutdown | A trace is sent in the background, so a stopping container could drop the last one. | The FastAPI lifespan hook calls a flush after the service stops. A failing flush is swallowed and only the class name is logged. | `test_service.py` has three added checks. Live: the third case's trace arrived through the stop-time flush. |
| Finding a case in Langfuse | Searching the case ID in the Tracing box found nothing, because that box does not search metadata or session IDs. The first instruction to search there was wrong. | The trace URL is computed from the case ID and opened directly; the Sessions page also lists the case. The method was checked against a known trace. | Three traces opened by direct URL. |
| Hidden classifier errors | The classifier's safe fallback hides API errors from the customer, so a failing key looked like a normal label. | The note `error: <Class>` is now in the trace metadata. | `test_tracing.py`. |
| Span timing | Spans are written after the reply is built, so each span lasts about 0.00 s. | The real total time is the `latency_ms` field in the metadata. Per-stage timing is deferred to Phase 6. | Visible in the three traces. |
| Secret-free tests in CI | Only some tests ran in the offline job. | The offline job installs from the lock file and runs six test files with no secrets and no database: desk logic, desk scoring, case ID, handler, tracing and service. | Green run after `8c46eac`. |
| A run that looked red | Run #11 showed "Cancelled" and looked like a failure. | The workflow has `cancel-in-progress: true`, so a newer push cancels an older run. It is not a failure. | Runs #10 and #12 and the run for `8c46eac` are green. |
| Terminal and shell habits | `load_dotenv()` never overrides a variable already set in the PowerShell window; `Read-Host` echoes unless `-AsSecureString`; Windows PowerShell 5 `Set-Content -Encoding UTF8` adds a BOM; a space can vanish at a terminal line wrap. | Variables were checked before each run, secrets were read as secure strings and never pasted into chat or git, and a missing space was confirmed against the source with a search. | The live run used the intended keys. |

Decisions (proposed in the notes and recorded as rows 055 to 062 in [decisions.md](../architecture/decisions.md)): the server makes the case ID and the trace ID comes from it (ADR-055); the queue holds proposed actions, approval only records, the database enforces the states (ADR-056); a least-privilege `desk_service` login (ADR-057); a reply never promises a review that did not happen (ADR-058); service controls (ADR-059); a container with no secret (ADR-060); metadata-only traces in four layers (ADR-061); CI with a separate secret-free job (ADR-062).

Done check: met. Gate G3 asks for evals in CI and a review queue. The eval gate is green with six secret-free tests beside it, the queue holds answers and proposed actions with database-enforced states, and the live run of 25 Nov produced three cases: two answers with citations and one hostile case that was queued as an open item, each with a trace and empty Input and Output.

Known limits:

- No agent calls `enqueue_action` yet, and nothing reads or decides queue items automatically. `scripts/show_review_queue.py` lists them. Three open hostile items are waiting.
- The queue row holds the customer's question and the reply, so that text is protected by access control, not by the trace layers.
- The daily cap counts requests, and one request can make up to 4 model calls.
- Limits live inside the process, so they reset on a restart and are not shared between containers.
- Span durations are near zero. Total time is in `latency_ms`.
- The container has been run locally only.
- The `desk_service` password and the 20 Nov owner password are due for rotation.
- Third-party GitHub Actions are not yet pinned to commit hashes.
- The untracked `eval/results` files stay uncommitted.
