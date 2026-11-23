# AOP Day 11 Notes: Attack Harness, Inspector Evidence and Gate G2

Nov 23, 2026 · @saurabh

## 1. Concepts we learnt

Day 11 was about proving the tool layer holds when someone attacks it. Nine ideas came out of it.

### 1.1 Adversarial testing (an attack harness)

Normal tests check that the happy path works. An attack harness plays the attacker: it sends hostile input and checks that the system holds. Example: asking `get_order` for `ord_1001 OR 1=1`, or asking `issue_refund` for 60.00 on an order worth 19.00.

### 1.2 The pass rule: refused AND nothing changed

An attack passes only if two things are true. The server refused the call, and the money and privacy tables are exactly as they were before. A refusal that still moved money would be a failure. Example: a refused refund must leave `ops.refunds` with the same row count.

### 1.3 Real servers, not mocks

The harness starts the real reader, writer and policy servers as child processes and talks to them over stdio, the way an AI agent would. A mock can pass while the real server fails, so mocks prove little here.

### 1.4 Four statuses and an exit code

Every attack ends as PASS, FAIL, KNOWN or SKIP. KNOWN means an accepted, documented gap. SKIP means the attack needed a server that did not start. The exit code is 0 when all are blocked, 1 when any FAIL, and 2 when there are only skips. A skip is never allowed to look like a pass.

### 1.5 The known-gap rule

A gap we cannot close today is written down, tested every run and shown in the report, not hidden. Example: attack D7. Any agent can cancel any customer's open deletion request, because the server does not know who is calling.

### 1.6 Strict input validation: ASCII digits only

The harness found that our id check was too loose. In Python's `re`, `\d` matches digits from other scripts, such as Arabic-Indic digits. We switched ids to `[0-9]`. Amounts were worse: `Decimal()` accepts `' 19.00'`, `'1_0.00'`, signs, full-width digits and `'19.00\n'`. Previews and tokens were issued for three of those. Amounts now have to match `[0-9]{1,9}(\.[0-9]{1,2})?` first.

### 1.7 Output schema as a contract

A tool can publish an output schema, and its answers must fit it. Our `purchased_at` was declared as a date-time while the database column is a date. The answer carried a timestamp with no time zone, so a strict client rejected every `get_order` answer.

### 1.8 MCP Inspector as a manual probe

Inspector is the official debug UI. It connects like an agent, lists the tools and lets you call them by hand. It found the schema bug the harness could not, because the harness checked refusals and never validated successful answers.

### 1.9 Layers of defence: client side and server side

Inspector showed no server refusal for `ord_1001 OR 1=1`. Most likely its form checks the id pattern before sending, which is a client-side check (still to confirm: no call line appears in the Messages pane). The server-side refusals are the ones that count, because a hostile agent will not use a polite client. Example: `ord_9999` has a valid format, so it reaches the server, which answers `No order found`.

### 1.10 Evidence for a gate

Gate G2 needs proof, not a claim. The proof is a saved run report plus six Inspector screenshots, all in `docs/evidence/`.

## 2. Why we need each concept

The tools can move money and start deletions, so a model that is fooled, or a person who is hostile, must not be able to do harm. A tool layer that is only tested on friendly input has not been tested.

- **Adversarial testing.** Unit tests only show that what we thought of works. Attacks show what we did not think of. Two real gaps (B4, B5) were found this way in one day.
- **Refused AND nothing changed.** An agent acts on the answer it gets. A refusal text proves little if a row was still written, so the state check is the real proof.
- **Real servers.** The risks sit in the wiring: roles, arguments, validation, the database login. A mock hides all of that.
- **Four statuses and an exit code.** A gate needs a single honest answer. Without SKIP, a server that failed to start would silently turn a test into a pass.
- **Known-gap rule.** Pretending a gap does not exist is worse than the gap. A KNOWN row with a reason lets a reviewer see the risk and who accepted it.
- **ASCII-only validation.** The server is the last line. Anything that reaches a database, an audit log or a prompt must be exactly the shape we expect.
- **Output schema as a contract.** Clients and agents rely on the published schema. If the server breaks it, strict clients fail, and lenient ones may misread the data.
- **Inspector.** A human can see what an agent sees. It finds problems in the tool description and the answer shape, which code tests do not look at.
- **Layers of defence.** A client check helps the user, but only the server check protects the data.
- **Evidence.** A gate that cannot be shown to a reviewer, or to an interviewer, was not really met.

## 3. How I implemented it in this project

The harness lives in `mcp/attacks/`. It ran 32 attacks on my machine: 31 blocked, 1 known gap, 0 failed, 0 skipped.

### 3.1 The harness

- `harness.py` holds the `Attack` decorator, the clients for the reader, writer and policy servers, a table-count snapshot, and the runner.
- Before each attack it counts rows in refunds, cancellations, deletion requests, approved or completed deletions, and export requests. After the attack it counts again and fails the attack if anything changed that the attack did not declare.
- It starts the reader and writer with `OPS_ROLE` set, and the policy server through `uv`. If the policy server fails to start, attacks that need it become SKIP.
- `run_attacks.py` runs all families or the letters you pass, and writes a Markdown report with a `--report` option.

### 3.2 The 32 attacks in six families

| Family | Attacks | What it tries |
| --- | --- | --- |
| A: Tool boundaries | A1 to A4 | Reader calls a write tool, writer calls a read tool, extra `role` arguments, exact tool lists per server |
| B: Input abuse | B1 to B5 | SQL text in ids, wildcards and paths, 10,000-character ids, non-ASCII digits and a trailing newline, odd amounts |
| C: Money abuse | C1 to C9 | Refund over the cap or over what is left on the order, missing, invented or superseded clauses, no token or a made-up token, a token reused for other arguments or for a cancellation, another customer's order, cancelling a one-off purchase (dry runs and refused commits only) |
| D: Privacy abuse | D1 to D7 | Unknown customers, two deletion requests in a row, cancelling when none is open, smuggling status or dates into the deletion tool, a deletion that can only ever be 'requested', export answers with counts only, and D7, the known gap |
| E: Leaks and poisoning | E1 to E3 | Raw contact data in answers, 14 error messages scanned for leaks, tool descriptions scanned for poisoning |
| F: Policy server | F1 to F4 | Hostile and malformed searches, prompt argument injection, the resource equals `config.py` |

### 3.3 What the harness and Inspector found

| Finding | Found by | Fix | Commit |
| --- | --- | --- | --- |
| Ids matched with `\d` accepted non-ASCII digits (B4) | Harness | Ids use `[0-9]` | `bf53ae3` |
| Amounts accepted spaces, signs, underscores, full-width digits, trailing newline (B5) | Harness | ASCII regex before `Decimal()` | `bf53ae3` |
| `purchased_at` declared date-time, database stores a date | Inspector | Type is `date`; new `test_output_schema.py` | `1065f68` |

### 3.4 Evidence

- `docs/evidence/g2-attack-run-2026-11-23.md`: the generated report (commit `bd3cf6a`).
- `docs/evidence/inspector/`: six screenshots (commit `467fe28`). They show the reader with four tools, the writer with five, the before and after of the schema bug, an unknown order refused, and an over-limit refund refused with no token.

### 3.5 What this run does not prove

- Splitting a refund across calls, and expired tokens, are proven below the transport only, not through the harness.
- There is no rate limit and no load test yet.
- D7 stays open. Each harness run also leaves cancelled deletion requests for `cust_002` and one open export request for `cust_001`, because no tool can cancel an export.

## 4. Architecture diagram of the day

&#91;embedded content: architecture of the day · harness, Inspector, three servers, database\]

The harness and Inspector reach the servers over the same stdio route an agent uses. The reader and writer talk to the database through different logins, so the harness counts the tables before and after each attack.

## 5. The architect's point of view

A control that is not attacked is a belief, not a control. Day 11 turned the beliefs from Days 7 to 10 into recorded evidence.

### 5.1 Defence in depth, with each layer tested

| Layer | What it stops | Where it is proven |
| --- | --- | --- |
| Tool list per server | A reader being asked to refund, a writer being asked to read | Family A, Inspector screenshots 1 and 5 |
| Input shape (ASCII ids and amounts) | Injection text, oversized and look-alike input | Family B |
| Business rules (cap, clause, token) | Over-limit, unjustified or replayed money actions | Family C, ADR-037 to ADR-039 |
| State machine and human approval | A deletion finishing without a person | Family D, ADR-042 |
| Output masking and schema | Leaked contact data, answers a strict client rejects | Family E, `test_output_schema.py` |
| Audit | Any refusal or action without a trace | Refusals and actions are audited; several attacks check the audit rows |

No single layer has to be perfect: each is meant to hold even if the one before it fails.

### 5.2 Trust boundaries

The model, the client and the user are all untrusted. The trust boundary is the server. The harness attacks from outside that boundary, over the real transport, so it tests the boundary and not our assumptions about it.

### 5.3 A gate is a decision, not a feeling

G2 has a definition: all attacks blocked or documented, no skips, a saved report, and screenshots. The report prints "G2 met" only for a full run with no FAIL and no SKIP. That keeps the decision honest when time is short.

### 5.4 Residual risk, owned

- **D7:** any agent can cancel any customer's open deletion request. The direction is safe, since it keeps data, and the action is audited. Closing it needs the server to know the caller, which is the next identity step.
- **No rate limit** on tools or on the policy server.
- **Limits of the check:** two attacks are proven below the transport only.
- **Test residue:** the harness leaves rows in the ops tables, so it must never run against production data.

### 5.5 What the Inspector adds

The harness tests behaviour. The Inspector tests the contract and the user experience: tool names, descriptions, schemas and the shape of answers. Both are needed, and the schema bug shows why.

## 6. Relevant diagrams

### 6.1 The life of one attack

&#91;embedded content: life of one attack · 2 decisions, 2 outcomes\]

Every attack is counted before and after, so a refusal that still changed a table fails. Two other results exist outside this flow: KNOWN for an accepted, documented gap such as D7, and SKIP when the server an attack needs did not start.

### 6.2 Client check and server check

&#91;embedded content: client check and server check · three Inspector calls\]

The injection text got no server answer in Inspector, most likely because the form blocks it before sending; that helps the person but is not a defence. The unknown order reached the server and was refused there. The third call shows the bug Inspector found: a valid answer that broke the published schema.

## 7. Architecture decisions tied to real-world cases

Three decisions came out of Day 11. The numbers ADR-047 to ADR-049 are proposed here and are written into `decisions.md` with the v0.11 page. ADR-047 rests on documented Python behaviour, not on an incident.

| Decision | Why | Real-world anchor | Rejected alternative |
| --- | --- | --- | --- |
| **ADR-047:** ids and amounts accept plain ASCII digits only, checked with `[0-9]` before any parsing | Python's `\d` matches digits from other scripts on text patterns, and `Decimal()` removes whitespace and underscores before reading a number | A Python core developer advises [never using `\d` and writing `[0-9]`](https://bugs.python.org/msg359695); a committer quotes the [Decimal rule on whitespace and underscores](https://bugs.python.org/msg394759). These are language behaviours, so no incident is needed | Normalise the text and accept it: the id in the audit log would then differ from what the caller sent |
| **ADR-048:** a gate attack passes only if it is refused and the tables are unchanged; accepted gaps are recorded as KNOWN; skips never count as a pass | An agent's words are not evidence. State is evidence | An AI agent [reportedly deleted a live database during a code freeze](https://fortune.com/2025/07/23/ai-coding-tool-replit-wiped-database-called-it-a-catastrophic-failure/) (Replit, July 2025): an instruction was not a control. A dealership chatbot [agreed to sell a Tahoe for $1](https://incidentdatabase.ai/entities/chevrolet-of-watsonville) (Dec 2023): no sale resulted, but a rule held only in the prompt did not hold. A tribunal [held Air Canada responsible](https://decisions.civilresolutionbc.ca/crt/crtd/en/525448/1/document.do) for what its chatbot told a customer about refunds (Feb 2024) | Check the refusal text only; or test against mocks |
| **ADR-049:** answers must fit the output schema the tool publishes, and `test_output_schema.py` checks it on every read tool | Clients and agents trust the schema. The MCP spec says servers [must return structured results that conform to it and clients should validate them](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) | Our own Inspector run: a valid order answer was rejected because `purchased_at` was typed as date-time | Loosen the schema to plain text, which hides future drift |

### 7.1 What each decision changed in the code

- **ADR-047:** `CustomerId` and `OrderId` patterns became `^cust_[0-9]{3}$` and `^ord_[0-9]{4}$`; amounts must match `[0-9]{1,9}(\.[0-9]{1,2})?` before `Decimal()` is called (commit `bf53ae3`).
- **ADR-048:** the harness fails any attack whose table counts change beyond what it declares, prints KNOWN for D7, and prints "G2 met" only for a full run with no FAIL or SKIP (commit `bd3cf6a`).
- **ADR-049:** `purchased_at` is a `date`, and the new test validates answers with strict `date` and `date-time` checks (commit `1065f68`).

### 7.2 Where the cases stop helping

The three cases are about agents acting, bots promising and tribunals deciding. None of them is a case about input validation or schema drift, so ADR-047 and ADR-049 stand on the language rules and the protocol text, not on an incident.

### Sources

- [Python issue tracker, advice to use `[0-9]` instead of `\d`](https://bugs.python.org/msg359695)
- [Python issue tracker, Decimal string rules](https://bugs.python.org/msg394759)
- [Fortune, Replit and the deleted database (23 Jul 2025)](https://fortune.com/2025/07/23/ai-coding-tool-replit-wiped-database-called-it-a-catastrophic-failure/)
- [AI Incident Database, Chevrolet of Watsonville chatbot (18 Dec 2023)](https://incidentdatabase.ai/entities/chevrolet-of-watsonville)
- [Moffatt v. Air Canada, 2024 BCCRT 149 (14 Feb 2024)](https://decisions.civilresolutionbc.ca/crt/crtd/en/525448/1/document.do)
- [Model Context Protocol, Tools specification (2025-06-18)](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
