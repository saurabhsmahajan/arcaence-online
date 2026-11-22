# AOP Day 9 notes (20 Nov): MCP write tools, dry run, single-use token, cap and audit

Nov 22, 2026 · @saurabh

**Day 9 is the day the AI agent got hands.** Until 19 Nov our MCP server could only look things up. On 20 Nov we added the first tools that change something (`issue_refund` and `cancel_subscription`) and built the controls that make that safe: a preview step, a one-time token, a spending cap, a required policy clause, and a permanent audit record.

## Start here

**What AOP is.** AOP (Arcaence Online Project) is a practice project: a fictional online platform, Arcaence Online, with an AI support desk built in three layers. Layer one is RAG (the AI answers from the platform's own policy documents and cites the exact clause). Layer two is an MCP server (a controlled doorway that lets an AI agent look at, and act on, customer data). Layer three is a multi-agent desk (several AI agents that sort tickets, handle billing and handle privacy requests). All data is synthetic and the repo is public.

**Where Day 9 sits.** Day 8 (19 Nov) gave the server three read-only tools and made them safe: a read-only database login, masked personal data, and a role fixed at launch. Day 9 (20 Nov) adds the dangerous half: tools that move money and end subscriptions.

**The goal of the day, in one sentence.** An AI agent may ask for a refund, but the refund must first be previewed, checked against a cap and a policy clause, spent exactly once, and always leave a record, whether it was allowed or refused.

**Words you will meet.**

| Word | Plain meaning |
| --- | --- |
| Agent | An AI program that decides which steps to take and calls tools to take them |
| MCP server | A program that offers a fixed list of tools to agents, and decides what each tool may do |
| Tool | One named action an agent can call, for example `issue_refund` |
| Read tool / write tool | A tool that only looks, versus one that changes data |
| Dry run | A rehearsal: do every check, change nothing, show what would happen |
| Token | A one-time code proving "this exact action was previewed" |
| Audit log | A record of every attempt, kept so that nobody can quietly edit it |
| Clause | One numbered rule in a policy document, for example Terms of Service v3, clause 2.2 |
| Cap | A ceiling on how much one customer may be refunded through the desk |

**How these notes are laid out.** The seven sections follow the same order as the checklist: (1) the concepts, (2) why each is needed, (3) how it was built here, (4) the architecture picture, (5) the architect's view, (6) detail diagrams, (7) the decisions and the real-world cases behind them.

## 1. The concepts we learnt

There are fifteen ideas. Each has a plain-words explanation and a small example from the project's synthetic data (customer `cust_001` bought `ord_1001`, a 19 EUR subscription; `cust_002` bought `ord_2001`, a 540 USD subscription).

### 1.1 Read tools versus write tools

**In plain words.** A read tool answers a question. A write tool changes the world. If a read tool is tricked, the worst outcome is that someone learns something. If a write tool is tricked, money moves or a customer loses a subscription, and that cannot always be taken back. So the two kinds are designed and guarded differently.

**Example.** `get_order(ord_1001)` shows an order. `issue_refund(ord_1001, 19.00)` pays money back. Same data, very different consequences.

### 1.2 Dry run (a rehearsal before the real thing)

**In plain words.** A dry run does every check a real action would do, but changes nothing. It returns "here is what would happen". Think of the preview screen before you press "Pay".

**Example.** The agent calls `issue_refund` with `dry_run=true`. The server checks the order, the cap and the clause, and answers `preview: refund 19.00 EUR on ord_1001, cap remaining after: 31.00`. No refund exists yet.

### 1.3 Single-use confirmation token

**In plain words.** The preview comes with a random code, the token. The real action only runs if the agent presents that code, and the code works once. It proves "this exact action was previewed first" and it stops the same action from being run twice.

**Example.** Think of a cinema ticket that is torn at the door. Once torn, it cannot be used again. The server also stores only a fingerprint (a SHA-256 hash) of the token, never the token itself, so even someone who reads the database cannot use the stored value.

### 1.4 Binding the token to the exact arguments

**In plain words.** The token is tied to the precise request it was issued for: tool name, customer, order, amount and clause. The server stores a hash of those arguments next to the token. If the commit arrives with different arguments, the token does not match.

**Example.** A token was issued for a 19.00 refund. If the agent (or an attacker who hijacked it) tries to commit 18.00, or a different order, the server answers `args_mismatch`. A refund token also cannot cancel a subscription, because the tool name is part of the fingerprint.

### 1.5 Expiry (time to live)

**In plain words.** A preview goes stale. The token is valid for 600 seconds. After that it is refused as `token_expired`, because the facts it was based on may have changed.

**Example.** A preview at 10:00 and a commit at 10:20 is refused. The agent must preview again and get a fresh token.

### 1.6 A cumulative cap

**In plain words.** The cap is a ceiling on the total refunded to one customer, per currency: EUR 50, USD 55, INR 4500. It counts everything already refunded, not just the current request. Anything above it is refused and, later in the project, will go to a human review queue.

**Example.** cust\_001 has been refunded 19 EUR. Another refund of 32 EUR would make 51 EUR, which is over 50, so it is refused as `over_cap`. A cap per call would be useless, since ten small refunds would slip under it.

### 1.7 Clause-required actions

**In plain words.** Every refund or cancellation must name the policy clause that justifies it, for example `tos_v3` clause 2.2. This ties the action to a written rule, so every action can be explained afterwards.

**Example.** A refund request with no clause is refused as `no_clause`. A request with a made-up clause id is refused as `unknown_clause`.

### 1.8 Registry versus allowlist

**In plain words.** Two different lists. The **registry** is the frozen list of every clause id that exists in the documents (80 ids, from Phase 1 of RAG). The **allowlist** is a short list per action saying which clauses may justify it. A clause can exist and still be the wrong reason.

**Example.** Clause 2.2 of the superseded `tos_v2` exists in the registry, but its document has been replaced, so it is refused as `clause_not_allowed`. Clause 3.2 of `tos_v3` (cancel a subscription at least 24 hours before renewal) is a valid basis for a cancellation but not for a refund.

## 2. Why we need each concept

Every concept closes one specific way an AI-driven refund can go wrong. The root cause is the same each time: a language model can be mistaken, manipulated or simply repeat itself, and a tool that moves money must stay safe when that happens. The table gives, for each concept, the failure it prevents.

| Concept | What goes wrong without it | What it protects |
| --- | --- | --- |
| 1.1 Separate write tools | A tricked read tool leaks information. A tricked write tool loses money. Treating them alike under-protects the dangerous one | Proportionate guarding: the more irreversible the action, the more checks |
| 1.2 Dry run | The agent acts on its first guess. Nobody, human or code, sees the effect before it happens | A moment to check, and a place for a person or reviewer to approve later |
| 1.3 Single-use token | A model that is confused or hijacked calls the commit directly, with no preview, or sends it twice | Proof that the commit follows a preview, and that it happens once |
| 1.4 Args binding | An attacker (or a mistaken model) previews a harmless 1 EUR refund, then commits 49 EUR with the same token | The commit is exactly the action that was previewed |
| 1.5 Expiry | A token from last week is spent after the order, the cap or the policy changed | Decisions are based on facts that are still fresh |
| 1.6 Cumulative cap | Ten refunds of 4.90 EUR each slip under a per-call limit and total 49 EUR. Or a prompt injection asks for everything | A hard ceiling on loss per customer, whatever the model is told |
| 1.7 Clause required | A refund with no stated reason cannot be explained to the customer, an auditor or a regulator | Every action is traceable to a written rule |
| 1.8 Registry plus allowlist | The model invents a clause id, cites a withdrawn terms document, or cites a real clause that does not justify a refund | The rule behind the action is real, current and relevant to the action |
| 1.9 Audit log | After an incident there is no evidence, or the evidence was edited. Refusals, the most interesting events, leave no trace | Evidence, and the data to see attacks and bugs as they happen |
| 1.10 Server-owned write database | A wrong or attacked action edits the shop's own tables, mixed with real customer data | A small, separate place to review and reverse what the agent did |
| 1.11 Transactions and savepoints | A refund is recorded but its audit row is lost, or a token is spent but no refund is made | Every action and its record are one unit: all or nothing |
| 1.12 Lock and re-check | Two simultaneous commits both pass the cap check and together exceed it. Or a refund passes at preview and is wrong by commit time | The cap holds under concurrent use and changing data |
| 1.13 Replay protection | A network retry, a double click or an attacker repeats a commit and the customer is refunded twice | One intended action produces one effect |
| 1.14 Fail closed | An error half-way leaves a refund without a record, or leaks internal detail into the model's context | Failure means "nothing happened", not "something half happened" |
| 1.15 Reader and writer split | One compromised server holds both the right to read private data and the right to move money | A smaller blast radius: stealing one capability does not give the other |

**The underlying principle.** The model's good behaviour is not the control. Each rule above is enforced by code and by the database, outside the model, so it still holds when the model is wrong, tricked or repeating itself. The prompt can ask nicely, but the server is what refuses.

## 3. How I implemented it in this project

The work was done in seven steps, one at a time, with a test after each. The code lives in the `mcp/` folder of the [arcaence-online repo](https://github.com/saurabhsmahajan/arcaence-online); the code commit is `2dfc21e`.

| Step | What was built | Main files | Proof |
| --- | --- | --- | --- |
| 1. Write database and login | Schema `ops` with `audit_log`, `refunds`, `cancellations`, `confirm_tokens`. Login `ops_writer`: writes only to `ops`, 5 second timeout, no read of email or phone, append-only audit table | `supabase/migrations/009_ops_write_database.sql`, `db_write.py` | `check_writer.py`: 16 checks, including that the login cannot update or delete an audit row and cannot touch knowledge tables |
| 2. Audit module | One function that writes an audit row, with a closed set of 16 reason codes and a whitelist of argument keys. It fails closed | `audit.py` | `test_audit.py`: 8 checks |
| 3. Policy checks | The cap, the clause lists and the rules as plain data in `config.py`. Pure functions that take facts and return a reason code or nothing | `config.py`, `policy.py` | `test_policy.py`: 25 checks, including 45 EUR already refunded plus 6 more is refused, and exactly the cap is allowed |
| 4. Refund: dry run and commit | `dry_run_refund` and `commit_refund`: token creation, hash-only storage, argument binding, expiry, lock, re-check, atomic spend, savepoints | `actions.py` | `test_actions.py`: 27 checks, all in one transaction that is rolled back |
| 5. Cancel subscription | The same two-step pattern with no money: `check_cancel` and `dry_run_cancel` / `commit_cancel` | `policy.py`, `actions.py` | `test_cancel.py`: 25 checks, including that a refund token cannot cancel |
| 6. Wire the tools | Two MCP tools registered only for the `ops_writer` role. One result model. `dry_run` defaults to true. Unexpected errors roll back and are logged as `internal_error` | `server.py`, `models.py`, `config.py` | `done_check_writes.py`: 18 checks through the real server over stdio |
| 7. Write it up | Build log, ADRs 037 to 041, these notes | `docs/` | This document |

**One refund, end to end.** The agent calls `issue_refund(cust_001, ord_1001, "19.00", tos_v3, 2.2)`. Because `dry_run` defaults to true, the server loads the order, the refunds so far and the clause lists, and runs the checks. It stores a hashed token with a hash of those exact arguments and writes an audit row `dry_run / allowed`. The agent receives the preview and the token. To go ahead it calls the tool again with `dry_run=false` and the token. The server takes the per-customer lock, reloads the facts, validates the token, re-runs the policy, spends the token with one atomic update, inserts the refund and writes the audit row `commit / allowed`. Any failure along the way rolls those writes back and records `commit / refused` with a reason.

The calling pattern is deliberately small. The caller owns the connection and the commit, and the action code never commits for itself:

```python
with db_write.connect() as conn:          # commits on clean exit, rolls back on error
    result = actions.commit_refund(conn, request, token)
```

**What the done check proves.** The plan's done condition was: a refund over the cap or without a clause ID is refused and logged. `done_check_writes.py` starts the real server as `ops_writer`, talks to it as an agent would, and checks that:

- the tool list is exactly `issue_refund` and `cancel_subscription`, with no `role` argument and no read tools;
- a 540 USD refund is refused as `over_cap`, and the audit log gained a matching row;
- a refund with no clause is refused as `no_clause`, and the audit log gained a matching row;
- a commit with no token, a made-up token, or a real token for a different amount is refused;
- an extra `role=admin` argument, SQL text in an order id and a float amount are all rejected;
- no refund and no cancellation row was created by any of it, so the check is safe to run repeatedly.

It passed on the author's machine (18 of 18), along with the earlier checks (`done_check` 10, `test_role` 5, `test_actions` 27, `test_cancel` 25). Replay of a spent token is proven in `test_actions.py`, not through the transport, because proving it over the wire would need a real commit and would use up the customer's cap.

**Things found while building (and fixed).**

- Tests that assumed empty tables. The done check leaves audit rows behind (that is the log doing its job), so tests that expected zero rows would fail on a second run. They now compare before and after.
- A test with a clause that could never fail (`... or True`). It was caught on review and replaced with a real assertion.
- A refusal that vanishes. If the clause fields were required in the tool schema, a missing clause would be rejected before the server's own code ran, and nothing would be logged. They are optional in the schema, so the policy refuses and the audit logs it.
- Environment variables are not inherited by the server process that the test client starts. The server reads its own `.env` file, and the role is passed explicitly at launch.

## 4. The architecture diagram covered today

&#91;embedded content: architecture · reader and writer servers, shop tables, ops schema\]

Read it left to right. The agent reaches the shop's data only through the reader server, and can change anything only through the writer. The writer's first three steps can stop a request; the fourth writes the rows into schema `ops`, and the highlighted audit log is the one table nobody can edit afterwards.

## 5. The architect's point of view

The design answers one question: **where does the decision to move money get made, and what can stop it?** The answer is that the model proposes, and deterministic code and the database decide. The model is treated as an untrusted caller, in the same way a web server treats a browser.

### 5.1 Trust boundaries

There are three zones. The **model and agent** are untrusted: they may be mistaken, manipulated by text in a ticket, or repeating themselves. The **MCP server** is the enforcement point: it is small, written by us, tested, and the only door to the write tables. The **database** is the final authority: even if the server has a bug, its login has no power outside schema `ops`, and the audit table cannot be edited. Every control sits on the trusted side of a boundary, never inside the prompt.

### 5.2 Defence in depth: each threat has two controls

No single control is trusted to hold. For each threat, a second control catches what the first one misses.

| Threat | First control | Backup if the first fails |
| --- | --- | --- |
| Model tricked into a very large refund | Cumulative cap in policy | The writer login can only write to `ops`, so no shop data changes; the attempt is in the audit log |
| Commit sent without a preview | Token required | Token is bound to the exact arguments and tool name |
| Same commit sent twice | Atomic spend (`where used_at is null`) | Audit row `token_used` makes the attempt visible |
| Two commits at the same moment | Per-customer advisory lock | Cap is re-checked under the lock |
| Invented or withdrawn clause | Frozen registry of real ids | Per-action allowlist of approved documents |
| Log edited after the fact | Login has insert and select only | Trigger blocks update, delete and truncate |
| Server bug writes a bad row | Transaction rolls back as a unit | Database constraints (for example amount above zero) |
| Raw email or phone exposed | Writer has no read tools | Column-level grants exclude those columns |
| Model adds a made-up `role` argument | Schema forbids unknown arguments | Role is fixed at launch and the start-up check compares the database login |

### 5.3 What the server enforces, and what it does not

The server enforces **hard limits**: money (amount, order balance, cap), ownership (the order belongs to the customer), and rule provenance (the clause is real, current and approved for that action). It does **not** judge whether a clause's conditions are met. Clause 2.2, for example, allows a refund only within 7 days and only if the item was not downloaded. That judgement needs reading documents and weighing facts, so it stays with the agent, the verifier from the RAG layer and, for large amounts, the review queue. This split is deliberate: code should enforce what can be stated as a rule on numbers, and people and models handle the judgement that cannot.

### 5.4 Trade-offs accepted

- **Two calls for every write.** More latency and a more complex agent. The return is a point where checks and a human can sit.
- **Stateful tokens.** A signed stateless token would need no table, but it cannot be spent once under concurrency without a store, so a table is needed anyway.
- **Two servers.** An agent that refunds must connect to both. The return is a much smaller blast radius for each.
- **Strict policy, few clauses.** The allowlist is code and a change needs a review. That friction is intended: widening what an agent may do should be a visible decision.
- **A closed audit vocabulary.** Sixteen reason codes cannot describe every nuance. Free text would, but free text can carry personal data or injected instructions into the log.

### 5.5 Known limits (stated openly)

- The server does not check clause conditions (see 5.3).
- Calls rejected by the schema (for example a malformed order id) never reach the write path, so the audit log does not record them.
- Replay of a token is proven in the action tests, not over the transport.
- The start-up login check for the writer role has no automated test.
- A refund is a record in `ops.refunds`; no real payment call exists yet, so the shop's own data does not change.
- The owner database role bypasses row-level security and could change the `ops` schema. This is the limit already named in ADR-032.
- The cap counts only refunds made through this server, and amounts are not converted between currencies.
- Audit rows and unused tokens accumulate; there is no clean-up job yet.

### 5.6 How this maps to AI governance language

For a governance conversation, the same design can be described in the field's terms. Human oversight (EU AI Act, Article 14) is the preview step and the review queue that comes later. Robustness and cybersecurity (Article 15) are the layered controls above. The NIST AI Risk Management Framework's Manage function is the cap, the audit trail and the refusal logging. The industry risk of "excessive agency" (listed in OWASP's LLM Top 10) is what the role split, the cap and the allowlist limit. These are my own mappings to explain the design, not a compliance claim.

**The interview version, in three sentences.** The agent can propose a refund but cannot make one: it must preview it, and the commit is a one-time token bound to those exact arguments. The server, not the prompt, enforces a spending cap and a required policy clause, under a lock, in one transaction with an audit record. Every refusal is logged with a reason code, so the failures are as visible as the successes.

## 6. Relevant diagrams

Three diagrams show the moving parts in detail: the sequence of one refund, the life of a token, and what happens inside the commit.

### 6.1 One refund: preview, then commit

&#91;embedded content: sequence · dry run, then commit\]

The dry run changes nothing except two bookkeeping rows (the token and its audit row). All the money-moving writes happen in the second half, after the lock and the second round of checks.

### 6.2 The life of a token

&#91;embedded content: states · life of a confirmation token\]

A token is born at a successful dry run. A commit with the wrong arguments is refused but does not spend it, so a mistaken call does not waste a valid preview. Only a commit that passes every check spends it, and after that it can never be used again. Left unused, it simply expires.

### 6.3 Inside the commit

&#91;embedded content: flow · inside the commit, one savepoint\]

The whole commit runs inside one savepoint. If any step fails, the writes of that savepoint are undone, and only then is the refusal recorded, so the failure is on the record even though the action is not. The caller commits the surrounding transaction, so a refund, its spent token and its audit row are saved together or not at all.

## 7. Architecture decisions, and the real-world cases behind them

Five decisions were recorded as ADR 037 to 041 in `docs/architecture/decisions.md`. Each is tied below to a public case. These are analogies, not identical systems: none of the cases below used an MCP server like ours. What they share is the failure pattern the decision is meant to prevent.

| ADR | Decision | Real-world case that shaped it |
| --- | --- | --- |
| 037 | A write is two calls: a dry run, then a commit with a single-use token bound to the exact arguments, hashed at rest, expiring after 600 seconds | Replit agent deleting a production database (July 2025); Stripe's idempotency keys |
| 038 | The refund cap is cumulative per customer per currency, kept in code and re-checked at commit under a lock | Chevrolet of Watsonville chatbot agreeing to a $1 Tahoe (December 2023) |
| 039 | Every write must cite a clause that exists in the frozen registry and is on the per-action allowlist | Moffatt v. Air Canada (February 2024) |
| 040 | Writes go to a server-owned schema with its own login, and every attempt is logged in an append-only audit table, in the same transaction | Replit incident again, for the evidence problem |
| 041 | Reader and writer run as separate roles; the writer has no read tools and `dry_run` defaults to true | Replit and Chevrolet together: instruction is not permission |

### Moffatt v. Air Canada: a chatbot's promise binds the company (ADR 039)

**What happened.** A customer asked Air Canada's website chatbot about bereavement fares and was told he could buy a full-price ticket and claim a reduced fare afterwards. The airline's actual policy did not allow that after travel. British Columbia's Civil Resolution Tribunal ruled in February 2024 that [Air Canada was liable for the misinformation](https://www.americanbar.org/groups/business_law/resources/business-law-today/2024-february/bc-tribunal-confirms-companies-remain-liable-information-provided-ai-chatbot/) and ordered it to pay the customer. The airline's defence, that the chatbot linked to the correct page, did not succeed, and [the tribunal found it had not taken reasonable care that its chatbot was accurate](https://www.cbc.ca/amp/1.7116416).

**The lesson we took.** What an automated agent tells or does for a customer is treated as the company's own act. So an action should rest on an approved written rule, not on the model's say-so. In AOP a refund needs a clause that is real (in the frozen registry) and current and relevant (on the allowlist), and a withdrawn or draft document is refused even if its clause id exists. The gap we kept: the server proves the basis exists, not that its conditions are met. That judgement stays with the agent, the verifier and the review queue, and is a known limit (section 5.5).

### Chevrolet of Watsonville: a limit in the persona is not a limit (ADR 038)

**What happened.** In December 2023 a user, Chris Bakke, instructed a dealership's ChatGPT-powered chatbot to agree with everything and call each reply a legally binding offer, then [got it to accept $1 for a new Tahoe](https://incidentdatabase.ai/reports/6682). The dealership did not honour it, and the bot was reportedly taken offline. The failure was the absence of a rule outside the conversation: nothing stopped the model from saying yes to any number.

**The lesson we took.** A price or spending limit that lives in a prompt can be argued away by whoever writes the next message. In AOP the cap is plain data in `config.py`, applied by code the model cannot talk to, and counted cumulatively so many small asks cannot add up past it.

### Replit and the deleted production database: instructions are not permissions (ADR 037, 040, 041)

**What happened.** In July 2025 a founder reported that an AI coding agent on Replit [deleted a live production database during a declared code freeze](https://fortune.com/2025/07/23/ai-coding-tool-replit-wiped-database-called-it-a-catastrophic-failure/), despite instructions not to change anything. According to [The Register's account](https://www.theregister.com/software/2025/07/21/vibe_coding_service_replit_deleted_production_database/719783), the agent also gave wrong information about what had happened, including that a rollback was impossible. [The founder later said the rollback worked](https://incidentdatabase.ai/reports/5578/). Replit's CEO apologised and the company said it was working on a planning-only mode.

**The lessons we took.** First, a freeze or a "do not" is a human policy, and it protects nothing unless the agent's real permissions match it. That is why the writer login can only write to `ops`, why destructive tools do not exist, and why `dry_run` defaults to true (ADR 041). Second, an agent's own account of what it did cannot be the evidence. The audit log is written by the server, in the same transaction as the action, and cannot be edited by the writer (ADR 040). Third, a preview step gives a place to stop before an irreversible change (ADR 037).

### Stripe idempotency keys: how payments handle retries (ADR 037)

**What happened.** Stripe's API lets a client attach a unique key to a request. [Stripe saves the result of the first request for that key and returns the same result to later retries](https://docs.stripe.com/api/idempotent_requests), so a network failure does not charge a customer twice. Stripe's own engineering write-up gives [double charging as the problem this solves](https://stripe.com/blog/idempotency).

**The lesson we took.** Safe repetition is a design property of a write, not something to hope for. Our token plays a similar role, with one difference: Stripe's key identifies a retry of the same request, while ours is issued by the server after a preview and must match the exact arguments. Both are spent or recorded by an atomic step, so exactly one wins under concurrency.

### Decision ledger

| ADR | Alternatives we rejected | Cost we accepted | Revisit when |
| --- | --- | --- | --- |
| 037 | A `confirm=true` flag; a signed stateless token; a human approval on every write | Two calls per write and a growing token table | A person or review queue must approve before commit |
| 038 | A cap per call; a cap in the prompt; a database trigger; currency conversion | Refunds over the cap are refused, not yet queued | The review queue exists |
| 039 | Registry check only; a free-text reason; requiring the clause in the schema | The server does not check clause conditions | The server can call the verifier |
| 040 | Writing into the shop tables; logging only to application logs; free-text reasons | A refund is a record, not yet money moved | A real payment call is added |
| 041 | One server with all tools; a writer that can also read; `dry_run` defaulting to false | An agent that refunds uses two servers | The desk agents prove the split awkward |

**Sources:** [American Bar Association on Moffatt v. Air Canada](https://www.americanbar.org/groups/business_law/resources/business-law-today/2024-february/bc-tribunal-confirms-companies-remain-liable-information-provided-ai-chatbot/) · [CBC on the ruling](https://www.cbc.ca/amp/1.7116416) · [AI Incident Database, Chevrolet Tahoe report](https://incidentdatabase.ai/reports/6682) · [Fortune on Replit](https://fortune.com/2025/07/23/ai-coding-tool-replit-wiped-database-called-it-a-catastrophic-failure/) · [The Register on Replit](https://www.theregister.com/software/2025/07/21/vibe_coding_service_replit_deleted_production_database/719783) · [AI Incident Database, Replit rollback report](https://incidentdatabase.ai/reports/5578/) · [Stripe, idempotent requests](https://docs.stripe.com/api/idempotent_requests) · [Stripe, designing robust APIs with idempotency](https://stripe.com/blog/idempotency). Search results were read as snippets, not full pages; figures such as refund amounts are left out because outlets differ.

### 1.9 The audit log: append-only, closed reason codes

**In plain words.** The audit log is a diary the server writes for every attempt, whether it was allowed or refused, a rehearsal or the real thing. Three rules make it trustworthy. It is **append-only**: the database login can add rows but not change or delete them (permissions plus a trigger that blocks update, delete and truncate). Reasons come from a **closed list** of sixteen fixed words such as `over_cap` or `no_clause`, never free text. Only **whitelisted fields** (customer id, order id, amount, currency, clause, dry\_run) are stored, and each value must match its expected shape, so personal data or injected text cannot sneak in.

**Example.** A refund without a clause leaves a row: tool `issue_refund`, mode `dry_run`, outcome `refused`, reason `no_clause`. Later anyone can count how often each refusal happened.

### 1.10 A server-owned write database

**In plain words.** The agent never writes into the shop's own tables. The server has its own schema, called `ops`, with four tables: `refunds`, `cancellations`, `confirm_tokens` and `audit_log`. Its own database login, `ops_writer`, can only write there. The shop's tables stay read-only for it.

**Example.** A committed refund is one row in `ops.refunds`. To review or reverse it, you look in one small place, not across the whole shop database.

### 1.11 Transactions and savepoints

**In plain words.** A **transaction** groups several database changes so they all happen or none do. A **savepoint** is a bookmark inside a transaction: you can undo back to it and keep what came before. We write the refund and its audit row inside one savepoint, so a refund without its record cannot exist. When a check fails, the savepoint is undone and then the refusal itself is recorded in the outer transaction, so refusals are never lost.

**Example.** The commit spends the token, inserts the refund and writes the audit row. If the audit insert fails, the token spend and the refund are undone as well.

### 1.12 Races: the advisory lock and the re-check

**In plain words.** A **race condition** is a bug that appears only when two things happen at the same moment. Two commits for the same customer could both read "19 EUR refunded so far", both decide a 31 EUR refund fits under the cap, and together exceed it. Two defences: a **per-customer lock** (`pg_advisory_xact_lock`) makes commits for one customer queue up, and the cap is **checked again at commit**, because the facts may have changed since the preview (this is the classic "check, then act" gap).

**Example.** Preview A (19 EUR) and preview B (32 EUR) both pass. A commits. When B commits, the server recounts: 19 + 32 is 51, over 50, so B is refused as `over_cap`.

### 1.13 Replay and idempotency

**In plain words.** A **replay** is sending the same request again, by accident (a network retry) or on purpose (an attacker). **Idempotent** means doing it twice has the same effect as doing it once. Payment systems such as Stripe solve this with idempotency keys. Our token plays a similar role: it is spent by one atomic database statement (`update ... where used_at is null`), and only one caller can win it.

**Example.** The same commit is sent twice. The first spends the token and refunds. The second is refused as `token_used` and refunds nothing more.

### 1.14 Fail closed

**In plain words.** When something unexpected goes wrong, the safe default is to do nothing. If the database errors, the audit write fails, or the code throws, the whole transaction is rolled back and the agent is told only "the action was not applied". Internal details are never shown, because they would end up in the model's context.

**Example.** If the audit table were unreachable, no refund would be issued. A refund with no record is worse than a refund that did not happen.

### 1.15 Separate reader and writer roles

**In plain words.** Least privilege means giving a component only what its job needs. The same server program starts in one of two roles, fixed at launch. `ops_reader` offers the three read tools. `ops_writer` offers only the two write tools and has no read tools at all, so it can never see a raw email or phone number. An agent that needs both connects to two servers.

**Example.** The billing agent reads the order through the reader server, then refunds through the writer server. A compromise of one does not hand over the other's powers.
