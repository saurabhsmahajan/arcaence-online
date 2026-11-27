# AOP Day 13 Notes: Case IDs, the review queue, the desk service, containers and tracing

Nov 27, 2026 · @saurabh

## 1. Concepts learnt

Day 13 (24 Nov plan row, finished late on 25 Nov) turned the desk from a function you call into a service you can run, watch and hand to other people. Ten ideas did that. Each one below says what it is in plain words, then gives an example.

### 1.1 Case ID: one name for one conversation

**In plain words.** A case ID is a label the server stamps on every message, so the reply, the review-queue item, the log line and the trace all point at the same thing. Ours looks like `case_20261125_f99a403f2dbf`: the date, then 12 random hex characters.

**Example.** A customer complains about a double charge. Support asks "which case?" With a case ID they open the exact queue item and the exact trace in seconds, without searching for names or message text.

**The rule that matters.** The server makes the ID. It never takes one from the caller, because a caller-chosen ID could be reused to collide with someone else's case.

### 1.2 Review queue: a waiting room for decisions a machine should not make

**In plain words.** When the desk cannot or should not decide (an angry customer, a threatened lawyer, an answer that failed verification), it writes an item to a table and a person looks at it later. There are two kinds. An *answer* item says "look at what the desk said". A *proposed action* item says "an agent suggests this action, and nothing happens until a person approves".

**Example.** A message says "my lawyer will be in touch about the refund". The customer gets a calm fixed reply, and a row appears in the queue with reason `hostile` and status `open`.

**The rule that matters.** Approving only records a decision. It does not run the refund. Running it is a separate step that stays under human control.

### 1.3 A state machine enforced by the database

**In plain words.** A state machine lists which statuses an item may move between. Ours: an answer item goes `open` to `resolved`; an action item goes `open` to `approved` or `rejected`; final states are final; nothing is ever deleted. We put these rules in the database itself, as a trigger, not only in Python.

**Example.** If a bug in our code tried to flip an approved refund back to `open`, the database would refuse. A decision also needs a name in `decided_by`, and the database stamps the time.

**Why the database.** Code has bugs and more than one program may write to the table. The database is the one door every writer passes through.

### 1.4 Least privilege for the service's database login

**In plain words.** Give a program only the permissions it needs. The `desk_service` login can read the policy tables, call the search function, and add or read queue items. It cannot update or delete anything, and it cannot see customers, the audit log or refunds.

**Example.** If someone stole this login, they could add junk queue rows. They could not read a customer record or change an existing row. We proved this with 15 probe checks, each rolled back.

### 1.5 Keep side effects out of the thinking function

**In plain words.** `desk_answer()` only thinks. It takes a message and returns a result, and it writes nothing. A second function, `handle_message()`, does the actions: it queues the item and records the trace.

**Example.** The evaluations and CI call `desk_answer()` with a read-only database login. If the thinking function wrote rows, every test run would need write rights.

### 1.6 The honesty rule when a side effect fails

**In plain words.** If the reply says "I am marking this for review" but the queue write failed, the reply is untrue. So the code swaps it for a fixed reply that promises nothing and points the customer to the Help Centre. Only the error's class name is kept, never its text, because the text could contain connection details.

**Example.** The database is down during a hostile complaint. The customer sees the no-promise reply, and the result records `queued: false` with the error class.

### 1.7 Controls around a service

**In plain words.** Five controls run before the desk does any work.

- **API key per client.** Each caller has a name and a secret; the check compares against every key in constant time.
- **Rate limit per client.** A token bucket refills steadily (10 a minute, burst of 5). Each request takes a token; an empty bucket means wait.
- **Daily cap.** At most 500 accepted requests a day.
- **Concurrency limit.** At most 4 requests at once; a fifth gets 503 "busy".
- **Safe errors.** A bad request never echoes the input back, a failure is a plain 500, and there is no `/docs` page.

**Example.** A client script loops and sends 1,000 requests. After the first few, the rest get 429 with a `Retry-After` header. After 500 in a day, the service says the daily limit is reached.

### 1.8 Containers: packaging the service with no secrets inside

**In plain words.** A container image is a sealed box holding the code, the libraries and the search model, so it runs the same anywhere. The image must hold no secrets; they are passed in when it starts. It runs as a non-root user, and a healthcheck asks `/healthz` every 30 seconds whether it is alive.

**Example.** `docker run -e DATABASE_URL ...` copies the value from your PowerShell window into the container. Nothing is written into the image, and we checked that it holds zero `.env` files.

### 1.9 Tracing: what happened inside one request, without the private text

**In plain words.** A trace is a timeline of one request's stages. Ours records metadata only: case ID, behavior, label, route, citation labels, attempts, queue result and latency. It never records the customer's message or the reply.

**Four layers keep the text out.** The trace is built from named fields only. A mask blanks text keys and long strings. An export guard deletes input and output from every span. A test reads the exported spans and fails if the message appears.

**Two more rules.** Tracing *fails open*: if Langfuse is down, the customer still gets an answer. And the service *flushes* traces when it stops, so the last ones are not lost.

**Example.** Three live traces in Langfuse, with Input and Output empty on all three.

### 1.10 CI that runs everything that needs no secret

**In plain words.** The pipeline has two jobs. The offline job runs six test files with no secrets and no database. The gate job runs the model-based evaluation with a read-only login and fails if the unsupported-claim rate rises.

**Example.** Run #11 showed a grey "cancelled" mark. Nothing had failed: the next push replaced it, because the workflow cancels an older run when a newer one starts.

## 2. Why each concept is needed

Each concept closes one specific failure, and the desk needed all ten once it started acting in the world (queueing, serving, tracing) instead of only answering.

| Concept | What goes wrong without it | What it gives you |
| --- | --- | --- |
| 1.1 Case ID | A reply, a queue item and a trace cannot be tied together, so support searches by message text, which is personal data. | One key opens everything about a case, with no personal text needed. |
| 1.2 Review queue | A hostile or unverifiable case gets a machine's answer, or is lost. | A person sees it. Later agents can only propose actions, never run them. |
| 1.3 State machine in the database | One buggy writer can reopen a decided refund or erase history. | The rules hold for every writer, and the record is permanent. |
| 1.4 Least privilege | A stolen service login can read customers and money tables. | The worst case is junk queue rows. |
| 1.5 Side effects kept out | Every evaluation and CI run needs write rights and fills the queue with test rows. | Evaluations run read-only, and all actions sit in one place. |
| 1.6 Honesty rule | The desk tells a customer a review is coming when the write failed. | A promise is made only when it is true. |
| 1.7 Service controls | One client or one loop can drain the model budget or hammer the service; error messages leak internals. | Spend is bounded: at most 500 requests a day with at most 4 model calls each. |
| 1.8 Container | The service works only on one machine, and secrets baked into an image travel with every copy. | The same image everywhere, secrets kept outside, and a non-root user limits the damage. |
| 1.9 Tracing | After a failure you guess which stage broke, or you log private text and create a second copy of customer data. | You see the stage that failed, with no message text stored. |
| 1.10 CI offline job and gate | A change breaks the service quietly, or secrets become reachable from a fork. | Every push proves the tests and the quality gate, with no secrets near untrusted code. |

The common thread: every new ability (queueing, serving, tracing) came with a matching limit, so the desk can do more without being trusted more.

## 3. How it was implemented in this project

Every concept is code on `main` with a test that fails if it breaks. The table maps each one to its files, its commit and its proof.

| Concept | Where it lives | Commit | Proof |
| --- | --- | --- | --- |
| 1.1 Case ID | `rag/case.py`; one line in `desk.py` | `dff5642` | `test_case.py`, 13 checks |
| 1.2, 1.3 Review queue and its state rules | `supabase/migrations/015_review_queue.sql`; `rag/review.py` (`enqueue_answer`, `enqueue_action`) | `ab01bc9`, `797fee2` | `test_review_queue.py` 27 checks, `test_review.py` 7 checks |
| 1.4 `desk_service` login | `supabase/migrations/016_desk_service_role.sql`; `rag/check_desk_role.py` | `165974c` | 15 probes, all rolled back, ending `DESK ROLE CHECK: PASS` |
| 1.5, 1.6 Handler and honesty rule | `rag/handler.py`; `QUEUE_FAILED_REPLY` in `rag/desk_logic.py` | `797fee2` | `test_handler.py`, 12 checks |
| 1.7 Service controls | `rag/service.py`, `rag/limits.py` | `f6c6741` | `test_service.py`, 35 checks, now 38 |
| 1.8 Container | `rag/Dockerfile`, `rag/.dockerignore` | `0b3fce5` | Container `healthy`; zero `.env` files in the image |
| 1.9 Tracing and flush on stop | `rag/tracing.py`; wired in `handler.py`; shutdown hook in `service.py` | `61a93e8`, `f1403da` | `test_tracing.py`, 26 checks; three live traces with empty Input and Output |
| 1.10 CI offline job | `.github/workflows/eval-gate.yml` | `8c46eac` | Both jobs green |
| Gate G3 | `docs/evidence/g3-eval-ci-review-queue-and-service-2026-11-25.md` | `be0abde` | Five conditions, one live run |

Three short pieces of code carry most of the ideas.

**The case ID** is made on the server, in UTC, with 48 random bits:

```python
CASE_ID = re.compile(r"case_[0-9]{8}_[0-9a-f]{12}")

def new_case_id(now=None):
    now = now or datetime.now(timezone.utc)
    return f"case_{now:%Y%m%d}_{secrets.token_hex(6)}"
```

**The honesty rule** lives in the handler, after the queue write is tried:

```python
if result["handoff"]["needed"]:
    try:
        result["review"]["item_id"] = str(enqueue_fn(result))
        result["review"]["queued"] = True
    except Exception as exc:  # the class name only
        result["review"]["error"] = type(exc).__name__
        if result["behavior"] == "escalate":
            result["answer"] = QUEUE_FAILED_REPLY
```

**The export guard** removes input and output from every span, whatever code set them:

```python
IO_ATTRIBUTES = ("langfuse.observation.input", "langfuse.observation.output",
                 "langfuse.trace.input", "langfuse.trace.output")

def drop_io(*, params):
    patches = {}
    for identifier, span in params.spans.items():
        found = tuple(k for k in IO_ATTRIBUTES if k in span.attributes)
        if found:
            patches[identifier] = OtelSpanPatch(delete_attributes=found)
    return MaskOtelSpansResult(span_patches=patches)
```

The live run on 25 Nov tied it together: a normal question was answered and traced, a hostile one was escalated, queued and traced, and a third question's trace survived `docker stop` because the service flushed on shutdown.

## 4. Architecture diagram: v0.13

&#91;embedded content: architecture v0.13 · one request path, two stores\]

A request enters the container through the service controls, then the handler runs the desk pipeline. Only the handler writes outward: a queue row when a person is needed, and a metadata-only trace. The review queue is highlighted because it is the new part that the 25 Nov desk agent will build on.

## 5. The architect's view

The design rule of Day 13 is to assume each layer will fail and make the next one hold, so no safety property rests on one check alone, whether that check is a prompt, a line of code or a person.

### Trust boundaries

There are four zones. The **caller** is untrusted. The **service** is trusted only as far as its login: `desk_service` can add queue rows and read policy, nothing more. The **database** enforces its own rules whatever the service does. **Third parties** (the model provider and Langfuse) receive only what we choose to send.

That last point is deliberate and uneven. The model provider must see the customer's message, because it answers it. Langfuse never does: it receives metadata only.

### Where each property is enforced

No property depends on a single layer. The table shows which layers hold each one.

| Property | Application code | Database | Infrastructure and CI |
| --- | --- | --- | --- |
| Only keyed callers get in | API key check against every key | none | Local container port published to `127.0.0.1` only |
| Spend is bounded | Rate limit, daily cap, concurrency limit | none | CI uses a dedicated key with its own spend limit |
| Queue states are valid | Python writes only valid rows | Trigger and constraints refuse invalid changes | `test_review_queue.py` |
| Least privilege | none | Role grants and a 10-second statement timeout | 15-probe role check |
| No message text in traces | Trace built from named fields; mask | none | Export guard; test reads exported spans |
| No secrets in images | `.dockerignore` excludes `.env*` | none | Secrets passed at start; image checked for `.env` files |

### Where personal text goes

The customer's message goes to exactly two places: the model provider, and the review queue when a person must look at it. The queue sits behind a database login and keeps the question so a reviewer can act. It does not go to logs or traces. One controlled home for personal text is easier to protect, to audit and to delete from than several.

### Failure modes we designed for

| What fails | What the customer sees | What is recorded |
| --- | --- | --- |
| Queue write fails | A fixed reply that promises nothing | `review.queued` false and the error class name |
| Langfuse is down or slow | A normal answer | A warning with the error class only |
| The classifier's API call fails | The normal answer path | `classifier_note` such as `error: BadRequestError` in the trace, so the hidden fallback is now visible |
| Verification fails after retries | The fixed not-found reply | A queue item with reason `verification_failed` |
| Too many requests or too busy | 429 or 503 with `Retry-After` | A log line with client name and case ID, no message text |
| The container is stopped | Nothing; in-flight work finishes | Pending traces flushed at shutdown |

### Trade-offs we accepted

- **Limits live in one process's memory.** This is simple and correct for one instance. Several instances would each allow the full limit, so they would need a shared store.
- **The daily cap counts requests, not tokens.** Because each request makes at most four model calls, spend is still bounded. Real token counts need the trace to carry usage, which is planned.
- **Traces carry no text.** We give up debugging by reading the conversation in the trace. In return a leaked or misconfigured trace project exposes no customer words.
- **Spans are written after the reply is built.** This keeps `desk_answer()` free of side effects, but Langfuse shows near-zero span durations. The real total is in `latency_ms`, and per-stage timing is deferred.
- **GitHub Actions are tagged, not pinned to commit hashes.** This is recorded debt.

### What changes at scale

A shared store for rate limits and the daily cap. A worker that reads the queue and a human screen that approves proposed actions. Token cost and stage timing in traces. A kill switch for write tools. The last item is the 28 Nov Phase 6 work.

## 6. Diagrams that explain the details

### The review queue states

&#91;embedded content: review item states · 4 states, 1 rule\]

An answer item can only become resolved. A proposed action can only become approved or rejected, and approving records the decision without running anything. Once decided, the row is final.

### Four layers of trace privacy

&#91;embedded content: trace privacy · 4 layers\]

No layer is trusted alone. The export guard was added after a probe showed that masking missed short text in input and output, and the fourth layer proves the result on real exported spans.

### The honesty rule when the queue fails

&#91;embedded content: queue failure · 1 decision\]

The reply depends on what actually happened. If the row was not written, the desk does not say a person will review it.

## 7. Architecture decisions and the real cases behind them

Eight decisions were taken on 24 and 25 Nov. They are not yet in `decisions.md`; the numbers below (ADR-055 to ADR-062) are proposed. Each decision names the option we did not take and one real case that shows why. Cases were checked against the pages linked under each one.

### ADR-055 (proposed): the server makes the case ID, and the trace ID comes from it

**Decision.** The case ID is random and dated, made on the server, never taken from the caller. The trace ID is computed from the case ID, so one case always maps to one trace.

**Not taken.** A caller-supplied ID, or a sequence number that reveals volume and can be guessed.

**Real anchor.** This is a design standard more than an incident. The [W3C Trace Context](https://www.w3.org/TR/trace-context-1/) recommendation defines a trace ID as 16 bytes written as 32 lowercase hex characters, and [Langfuse's SDK](https://langfuse.com/docs/observability/sdk/upgrade-path/python-v2-to-v3) requires the same shape and can derive one from a seed. Using the case ID as that seed keeps one identifier across the reply, the queue item and the trace.

### ADR-056 (proposed): proposed actions are queued, approval only records a decision, and the database enforces the states

**Decision.** An agent may propose an action. A person approves or rejects it, and approving executes nothing. The status rules sit in a database trigger, so no writer can skip them.

**Not taken.** Letting an agent run "low-risk" actions directly, or keeping the rules only in Python.

**Real case.** In July 2025 the founder of SaaStr reported that Replit's AI agent [deleted his production database](https://www.theregister.com/software/2025/07/21/vibe_coding_service_replit_deleted_production_database/719783) despite instructions to change nothing without permission. Replit's response, reported by [The Register on 22 July 2025](https://www.theregister.com/2025/07/22/replit_saastr_response/), was to separate development and production databases and offer backups with one-click restore. Its CEO called the incident "Unacceptable and should never be possible."

**Lesson.** An instruction to an agent is not a control. A permission the agent does not hold is.

### ADR-057 (proposed): the service runs as `desk_service`, a login that can only read policy and add queue rows

**Decision.** A separate database login with select on four knowledge tables, execute on the search function, and select and insert on the queue. No update, no delete, no customers, no audit log, a 10-second statement timeout.

**Not taken.** Reusing the owner login or the broader writer login because it was already set up.

**Real case.** The 2019 Capital One breach started with a server-side request forgery on a web application firewall. That firewall's role could list and read more than 700 storage buckets, [although a firewall only needs to filter traffic](https://www.breachsense.com/blog/capital-one-data-breach-case-study/). In August 2020 the OCC imposed an [$80 million penalty](https://www.insurancejournal.com/news/national/2020/08/07/578265.htm), citing a failure to identify and manage cloud risks and insufficient network security and data loss prevention controls.

**Lesson.** A flaw in one component is survivable when that component's credential reaches little. Here it reached a very large amount.

### ADR-058 (proposed): a reply never promises a review that did not happen

**Decision.** If the queue write fails, the escalate reply is replaced by a fixed one that promises nothing. The result records `queued: false` and the error class name only.

**Not taken.** Keeping the "I am marking this for review" wording and retrying quietly.

**Real case.** In [Moffatt v. Air Canada, 2024 BCCRT 149](https://decisions.civilresolutionbc.ca/crt/crtd/en/525448/1/document.do), decided on 14 February 2024, a tribunal held the airline responsible for wrong information its website chatbot gave about bereavement fares. [CBC reported](https://amp.cbc.ca/lite/story/1.7116416) an order to pay $812, the gap between the bereavement rate and the full fares paid.

**Lesson.** What the desk says on screen is the company's statement. A promise that is false when made is a liability, so a promise must be conditional on the action having happened.

### ADR-059 (proposed): the service limits who calls it and how much it can spend

**Decision.** One API key per client, a token-bucket rate limit, a daily cap of 500 accepted requests, a limit of 4 requests at once, a message length limit of 2,000 characters, and errors that never echo input.

**Not taken.** Relying on the model provider's own limits as the only protection.

**Real anchor.** OWASP lists [Unbounded Consumption (LLM10:2025)](https://genai.owasp.org/llmrisk/llm10) as a top risk for LLM applications. It includes denial of wallet, where a high volume of operations exploits pay-per-use pricing, and it recommends input limits, rate limits and quotas.

**Lesson.** A service that calls a paid model can be harmed without ever going down. The bill is the outage, so a cap has to be a control of the service, not a note in a budget.

### ADR-060 (proposed): the container holds no secret, runs as a non-root user, and takes its settings at start

**Decision.** `.dockerignore` excludes `.env*`, secrets arrive with `docker run -e`, the process runs as an unprivileged user, and a healthcheck watches `/healthz`. A check proves zero `.env` files are in the image.

**Not taken.** Copying `.env` into the image for convenience.

**Real case.** A [2023 study from RWTH Aachen University](https://www.comsys.rwth-aachen.de/publication/2023/2023_dahlmanns_secrets-revealed-in-container/) analysed 337,171 Docker Hub images and content from 8,076 other private registries. It found that 8.5% of images contained secrets, including 52,107 private keys and 3,158 API secrets. The leaked keys were used in practice: 1,060 certificates relied on compromised keys, and 275,269 TLS and SSH hosts used leaked private keys.

**Lesson.** An image is copied, cached and shared. Whatever is baked in travels with every copy.

### ADR-061 (proposed): traces carry metadata only, in four layers, fail open, and flush at shutdown

**Decision.** Traces are built from named fields, masked, stripped of input and output at export, and tested. A tracing failure never changes the reply, and the service flushes pending traces when it stops.

**Not taken.** Recording the customer's message and the answer in the trace to make debugging easier.

**Real case.** Ireland's Data Protection Commission [fined Meta Ireland €91 million on 27 September 2024](https://www.dataprotection.ie/news-media/press-releases/DPC-announces-91-million-fine-of-Meta). Passwords had been stored in plaintext on internal systems, which the regulator found breached the security principle and the security-of-processing article of the GDPR (Articles 5(1)(f) and 32(1)), among other findings. [The Irish Times reported](https://www.irishtimes.com/business/2024/09/27/facebook-owner-meta-fined-91m-by-irish-data-protection-commission) that Meta described the passwords as having been logged in a readable format within internal data systems.

**Lesson.** Observability data is a second copy of whatever you put in it, and it is copied widely and kept long. Sensitive text belongs in one controlled place, not in logs and traces.

### ADR-062 (proposed): CI runs the secret-free tests in a separate job, never on pull requests, and the gate uses a read-only login

**Decision.** The offline job runs six test files with no secrets. The gate job, which holds secrets, runs only on pushes to `main`, with a read-only database login. Pinning actions to commit hashes is recorded as debt.

**Not taken.** Running every test in the one job that holds the secrets, or triggering it from pull requests.

**Real case.** In March 2025 the popular GitHub Action tj-actions/changed-files was compromised, and CISA added it to its [Known Exploited Vulnerabilities Catalog](https://www.cisa.gov/news-events/alerts/2025/03/18/supply-chain-compromise-third-party-github-action-cve-2025-30066) as CVE-2025-30066. [SentinelOne's record](https://www.sentinelone.com/vulnerability-database/cve-2025-30066) says the attacker moved repository tags to a malicious commit on 14 March 2025.

**Lesson.** A tag is a pointer that can be moved, and a job that holds secrets can be made to print them. Keep secrets in as few jobs as possible, and pin what those jobs run.

### Sources

- [W3C Trace Context](https://www.w3.org/TR/trace-context-1/) and [Langfuse Python SDK upgrade guide](https://langfuse.com/docs/observability/sdk/upgrade-path/python-v2-to-v3)
- [The Register, 21 Jul 2025](https://www.theregister.com/software/2025/07/21/vibe_coding_service_replit_deleted_production_database/719783) and [22 Jul 2025](https://www.theregister.com/2025/07/22/replit_saastr_response/)
- [Breachsense Capital One case study](https://www.breachsense.com/blog/capital-one-data-breach-case-study/) and [Insurance Journal, 7 Aug 2020](https://www.insurancejournal.com/news/national/2020/08/07/578265.htm)
- [Moffatt v. Air Canada decision](https://decisions.civilresolutionbc.ca/crt/crtd/en/525448/1/document.do) and [CBC, 15 Feb 2024](https://amp.cbc.ca/lite/story/1.7116416)
- [OWASP LLM10:2025](https://genai.owasp.org/llmrisk/llm10)
- [RWTH Aachen, Secrets Revealed in Container Images](https://www.comsys.rwth-aachen.de/publication/2023/2023_dahlmanns_secrets-revealed-in-container/)
- [Irish DPC press release](https://www.dataprotection.ie/news-media/press-releases/DPC-announces-91-million-fine-of-Meta) and [The Irish Times, 27 Sep 2024](https://www.irishtimes.com/business/2024/09/27/facebook-owner-meta-fined-91m-by-irish-data-protection-commission)
- [CISA alert on CVE-2025-30066](https://www.cisa.gov/news-events/alerts/2025/03/18/supply-chain-compromise-third-party-github-action-cve-2025-30066) and [SentinelOne CVE record](https://www.sentinelone.com/vulnerability-database/cve-2025-30066)
