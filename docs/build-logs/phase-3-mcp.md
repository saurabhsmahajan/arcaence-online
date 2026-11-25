# Phase 3: MCP server (19 Nov 2026 onward)

Status: in progress. The 19 Nov, 20 Nov, 21 Nov and 22 Nov rows are done.

## 19 Nov: read tools, masked data, role fixed at launch

A new folder `mcp/` holds a server with three read tools (`get_account`, `get_order`, `get_subscription`). It connects with its own database role, masks personal data before a reply leaves the server, and takes its role from the launch environment, never from an argument. Findings:

| Area | Finding | How we handle it | Check |
| --- | --- | --- | --- |
| Database access | The AOP Python code connects as the owner role, which bypasses row-level security. This was the known limit in ADR-032. | Migration 008 creates `ops_reader`: `select` on `customers`, `orders` and `invoices` only, `default_transaction_read_only = on`, a 5 second statement timeout, and one select policy per table. The password is set outside git. | `check_role.py`: reads work, insert and update fail with `ReadOnlySqlTransaction`, the knowledge tables fail with `InsufficientPrivilege`. |
| Nothing to mask | `customers` had no contact data. | Migration 008 adds synthetic `email` and `phone` (`example.com` and `+00` numbers). | Masked output in `try_tools.py`. |
| Input shape | Ids reach SQL. | Ids must match `^cust_\d{3}$` and `^ord_\d{4}$`. SQL uses parameters. A malformed id is refused before any query runs. | `done_check.py`: an id with SQL text is refused. |
| Output shape | A reply can only carry fields the model names. | Output models forbid extra fields. `Account` has `email_masked` and `phone_masked` and no raw field, so no code path can return a raw value. | `test_masking.py`: the raw email and phone appear nowhere in the tool output. |
| Masking | Masking in a prompt or in the model's answer is too late. | Masking happens in the server. `a***@example.com`; `+** **** **01` keeps the last two digits. A value that does not parse becomes `***`. | `test_masking.py`. |
| Unknown arguments | The SDK (mcp 2.3.0) silently ignores an argument a tool does not declare, so `role="admin"` was accepted and dropped. Found by testing, not by reading the docs. | At startup each tool's argument model is set to forbid extras, so every schema says `additionalProperties: false` and the call is rejected. This uses internal SDK attributes. | `test_role.py` and `done_check.py` fail if a later SDK release changes them. |
| Role | A role the model could influence is not a role. | `OPS_ROLE` is read once at start. An unknown role stops the process. Only the role's tools are registered. At startup the server asks the database for `current_user` and refuses to start if it is not the expected role. | `test_role.py`. |
| SDK version | `FastMCP` became `MCPServer` in mcp 2.x, so most examples fail on import. | Code written and tested for 2.3.0 (`from mcp.server.mcpserver import MCPServer`). | Import works on the machine. |

Decisions: a dedicated read-only database role for the MCP server (ADR-034); masking in the server with output models that have no raw fields (ADR-035); role fixed at launch with unknown arguments forbidden (ADR-036).

Done check: met. `done_check.py` starts the real server over stdio and finds the three tools, masked output for both customers, and refusal of `role=admin`, `role=ops_writer`, an id with SQL text and a write tool that does not exist.

Known limits:
- `display_name` is returned as is. It is synthetic here. A real name is personal data and would be cut to a first name or initials.
- `ops_reader` can read the raw email and phone columns. Only the tool layer masks them. Column-level grants would remove that.
- The extra-argument fix relies on internal SDK attributes.
- Every call opens a new database connection. There is no pool.
- The server has no audit trail of who called what.
- Tools take a customer id as given. The server does not check that the caller is allowed to see that customer. Who may ask for which customer is desk logic, planned for later.
- Only the read role exists. Write tools and a second role are later work.

## 20 Nov: write tools, dry run, single-use token, cap and audit

The same server now starts in a second role, `ops_writer`, that offers `issue_refund` and `cancel_subscription`. A write is two calls: a dry run that previews and returns a token, then a commit that must present it. A refund over the cap or without a clause is refused and logged. A refund is a record in our own schema `ops`; no payment call exists yet. Findings:

| Area | Finding | How we handle it | Check |
| --- | --- | --- | --- |
| Where writes go | Writing into the shop tables would mix agent actions with real customer data, and the owner connection bypasses row-level security (ADR-032). | Migration 009 creates schema `ops` (`refunds`, `cancellations`, `confirm_tokens`, `audit_log`) and a login `ops_writer`: writes only to `ops`, 5 second timeout, select on orders and invoices, select on customers without email and phone. The password is set outside git. | `check_writer.py`: 16 checks, including that the writer cannot read email or phone and the reader cannot read `ops`. |
| Audit | Nothing recorded who asked what (a known limit from 19 Nov). | Every attempt writes an audit row: allowed or refused, dry run or commit, a reason from a closed list of 16 codes, arguments from a whitelist of keys. The table is append-only through insert-only grants plus a trigger on update, delete and truncate. If the audit write fails the action fails. | `check_writer.py` (cannot update, delete or truncate), `test_audit.py`: 8 checks. |
| Spending limit | A cap per call is beaten by many small refunds. | A cumulative cap per customer per currency in `config.py` (EUR 50, USD 55, INR 4500), checked at the dry run and again at commit under a per-customer advisory lock. | `test_policy.py`: 25 checks, including 45 received plus 6 asked refused and exactly the cap allowed. |
| Reason for an action | A real clause id can still be the wrong reason: superseded and draft documents exist in the frozen registry. | A clause is required. It must be in the frozen registry and on a per-action allowlist. | `test_policy.py`: superseded, draft and refund-only clauses refused. |
| Repeat and tamper | A commit can be repeated, or sent with other arguments than the ones previewed. | A token is random, single-use, valid for 600 seconds, stored only as a hash, bound to a hash of the exact arguments and the tool name, and spent by one atomic update. A mismatch does not spend it. | `test_actions.py`: 27 checks. `test_cancel.py`: 25 checks, including that a refund token cannot cancel. |
| Partial writes | A refund could exist without its record. | The write and its audit row run in one savepoint. A refusal undoes the savepoint and is then recorded in the outer transaction, so refusals are kept. | `test_actions.py`, run in one transaction that is rolled back. |
| Refusals that vanish | If the clause fields were required in the tool schema, a missing clause would be rejected before our code ran and nothing would be logged. | Clause and amount are optional in the schema, so policy refuses and audit logs. Ids keep strict patterns. | `done_check_writes.py`. |
| Tests assuming empty tables | The done check leaves audit rows, so tests expecting zero rows failed on a second run. | The action tests compare before and after. A check ending in `or True` was caught in review and replaced. | Second run of `test_actions.py` and `test_cancel.py` after the done check. |
| Roles of the server | The writer has no use for read tools and should not see contact data. | `OPS_ROLE` accepts `ops_reader` or `ops_writer`. The writer registers only the two write tools. At start the server checks the database login against the role, through the writer connection for the writer. | `done_check_writes.py`: exactly two tools, no `role` argument, `get_account` does not exist. |

Decisions: dry run and single-use token (ADR-037); cumulative cap (ADR-038); clause required, registry plus allowlist (ADR-039); server-owned write schema and append-only audit (ADR-040); separate reader and writer roles with `dry_run` defaulting to true (ADR-041).

Done check: met. `done_check_writes.py` starts the real server as `ops_writer` over stdio and finds exactly the two write tools; a 540 USD refund refused as `over_cap` and logged; a refund with no clause refused as `no_clause` and logged; a commit with no token, a made-up token or a different amount refused; an extra `role` argument, SQL text in an id and a float amount rejected; no refund or cancellation row created. It moves no money, so it can be run repeatedly. 18 checks passed. The 19 Nov checks still pass (`done_check.py` 10, `test_role.py` 5).

Known limits:
- The server enforces money, ownership and rule provenance. It does not check that a clause's conditions are met (for example 2.2: within seven days and not downloaded). That stays with the agent, the verifier and the review queue.
- A call rejected by the schema (unknown argument, malformed id) never reaches the write path, so the audit log does not record it.
- Replay of a token is proven in `test_actions.py`, below the transport, because proving it over the wire would use up the cap. The per-customer lock is not exercised by a concurrent test.
- The start-up login check for the writer has no automated test.
- A refund is a record. No payment call exists and the shop tables do not change.
- The owner role can still change the `ops` schema and drop the audit trigger (the limit in ADR-032).
- The cap counts only refunds made through this server, and amounts are not converted between currencies.
- Audit rows and unused tokens accumulate; there is no clean-up job.
- The clause allowlists are code, read from `config.py`, and the registry is read from a file in the repo.
- Refunds over the cap are refused, not queued. The review queue is planned for 24 Nov.

## 21 Nov: privacy tools, accessibility tool, policy server, resource and prompt

The ops server gains four tools, one resource and one prompt, and a second MCP server answers policy questions. A customer can now ask for a data export or an account deletion, but the AI can only file the request. A person approves it, and a database trigger refuses completion until a 7-day cooling-off has passed. Findings:

| Area | Finding | How we handle it | Check |
| --- | --- | --- | --- |
| Deletion cannot be undone | A tool that deleted on request would let anyone who can talk to the chat erase a customer. | Migration 010 creates `ops.deletion_requests` with the states requested, approved, completed, rejected and cancelled. A trigger allows only the listed moves, blocks delete and truncate for everyone including the owner, locks the decision fields after approval, and refuses writer approve, reject or complete. The 7-day cooling-off starts at approval. A unique partial index allows one open request per customer. | `test_deletion_states.py`: 20 checks. |
| What the AI may do | The AI should file and cancel, not decide. | No tool approves, rejects or completes a deletion. `ops_writer` has select, insert and update on two columns (`status`, `cancelled_by`). The tool path can only produce `requested` or `cancelled`. | `test_privacy_deletion.py`: 16 checks. `done_check_privacy.py`: 14 checks over the real server, including that a deletion cannot complete in one call. |
| Export leaks | Returning a customer's data in chat would leak it through a shared or hijacked session. | Migration 011 creates `ops.export_requests`. The tool returns counts of orders and invoices only. A person who is not the writer confirms identity and sends the copy. | `test_privacy_export.py`: 17 checks. |
| Privacy audit | Privacy attempts must be as traceable as refunds. | Each attempt writes an audit row in mode `commit` with clause `tos_v3 5.2`. Two reason codes are added, `request_already_open` and `no_open_request`, so there are now 18. | `test_privacy_deletion.py`, `done_check_privacy.py`. |
| Reader needs one clause | The reader login has no rights on the knowledge tables but must give the accessibility statement. | Migration 012 adds `public.accessibility_statement()`, a security-definer function with no arguments that returns clause 6.4 of the approved `tos_v3`. Execute goes to `ops_reader` and `service_role`. The tool `get_accessibility_info` calls it. | `test_accessibility.py`: 9 checks. |
| Policy search shares a trust domain | Policy text is edited by others and the search should not carry the power to touch customers or money. | A separate server, `policy_mcp`, with its own folder, dependencies (`fastembed`, `BAAI/bge-small-en-v1.5`, 384 dimensions) and login `policy_reader` (migration 013: read-only sessions, 5 second timeout, execute on `search_policy(vector,int)` only). Results carry citations and a note that passages are reference text, not instructions. A database error gives a generic message. | `test_policy_server.py` 17, `test_policy_login.py` 11, `done_check_policy.py` 8. |
| Reference data can drift | A second copy of the refund limits would disagree with the checks sooner or later. | The resource `arcaence://refund-limits` is built from `config.py`. The prompt `investigate_refund_case` takes ids that must match `^cust_\d{3}$` and `^ord_\d{4}$`, so no free text enters the template. | `test_reference.py`: 16 checks. |
| Tests assuming empty tables | The done check commits cancelled requests, so later runs saw leftover rows. Rows created in one transaction share a timestamp. | Tests read a baseline first, sort status lists and filter owner-side updates by status. | Second run of all privacy suites after the done check. |
| Missing tools on the machine | The plan step assumed `supabase db push`, but the CLI is not installed. | Migrations are applied with `scripts/apply_sql.py`. | Migrations 010 to 013 applied and verified. |

Decisions: deletion as a database-enforced process with human approval and cooling-off (ADR-042); export returns counts only (ADR-043); accessibility statement through a narrow security-definer function (ADR-044); a separate policy MCP server with its own login (ADR-045); reference material from one source with validated prompt arguments (ADR-046).

Done check: met. "Deletion never completes in one call" holds at three levels: no tool exists to approve or complete a request; the tool path can only produce `requested`, shown through the real stdio server in `done_check_privacy.py`; and the database trigger refuses an out-of-order move and completion before the cooling-off ends. A 14-suite regression run of all earlier work also passed.

Known limits:
- The server does not check clause conditions. That stays with the agent, the verifier and the review queue.
- The owner role can still change the `ops` schema (the limit in ADR-032).
- The scripts for approving, completing and rejecting a deletion, and for fulfilling an export, do not exist yet. Today a person does those steps with plain database operations.
- The embedding model name is written in both `rag` and `policy_mcp`. A mismatch would give poor search results, guarded only by a config constant.
- An AI could cancel a legitimate deletion request. This is the safe direction, and it is audited.
- The policy server has no rate limit.
- The owner database password was shared in chat on 20 Nov. Rotating it is still open.

## 22 Nov: attack harness, Inspector evidence and gate G2

No new tool this day. A harness in `mcp/attacks/` plays the attacker against the real reader, writer and policy servers over stdio, and MCP Inspector is used by hand on the same servers. An attack passes only if the call is refused and the money and privacy tables are unchanged. The work found three real defects, all fixed.

| Area | Finding | How we handle it | Check |
| --- | --- | --- | --- |
| Proving the controls | Unit tests show each control works when called directly, not that the servers hold under hostile input over the real transport. | `mcp/attacks/`: 32 attacks in six families (privilege, injection, money, privacy, leaks and poisoning, policy server). Each attack counts the ops tables before and after. Statuses are PASS, FAIL, KNOWN and SKIP, with exit codes 0, 1 and 2. | `docs/evidence/g2-attack-run-2026-11-23.md`: 31 PASS, 1 KNOWN, 0 FAIL, 0 SKIP. |
| Ids with non-ASCII digits (B4) | The id patterns used `\d`, which in Python text patterns also matches digits from other scripts. | Patterns are now `^cust_[0-9]{3}$` and `^ord_[0-9]{4}$` in `models.py` and `reference.py`. This amends the patterns quoted in ADR-046. | B4; `test_reference.py` still passes. |
| Odd amounts (B5) | `Decimal()` removes whitespace and underscores and accepts signs and full-width digits. A preview and token were issued for `' 19.00'`, `'1_0.00'` and `'19.00\n'`. | An ASCII regex, `[0-9]{1,9}(\.[0-9]{1,2})?`, runs before `Decimal()` in `policy.py`. | B5; `test_policy.py` (25), `test_actions.py` (27), `test_cancel.py` (25) pass. |
| Output contract | Inspector rejected a valid `get_order` answer: `purchased_at` was declared as a date-time while the column is a date, so the value was a timestamp with no zone. The harness had missed it because it checked refusals and never validated successful answers. | The type is `date`. New `test_output_schema.py` validates every read tool's answer against its published schema with strict `date` and `date-time` formats. It failed on the old code and passes on the fix. | Inspector screenshots 2 and 3; `test_output_schema.py` (10 checks). |
| A test that changed what it checked | Attack D5 first failed its own state check because it also called `request_data_export`, which writes a row. | The call was removed. Attacks declare which tables they may change (`may_change`), and anything else fails the run. | D5 passes. |
| Runs leave rows | Each run leaves cancelled deletion requests for `cust_002` and one open export request for `cust_001`. No tool can cancel an export. | Declared in the attacks and recorded as a limit. The harness must not run against production data. | Report section "What this run does not cover". |
| Inspector and the role | Inspector did not pass the shell's `OPS_ROLE` to the server it started, so the writer run first showed the reader's four tools. The default role is the reader, which is the safe direction. | The role is passed to Inspector with `-e OPS_ROLE=ops_writer`. | Inspector screenshots 1 and 5. |

Decisions: ASCII-only ids and amounts (ADR-047); the pass rule, KNOWN gaps and skips that never count as a pass (ADR-048); answers must fit the published output schema, with a test (ADR-049).

Done check: met. The full run is recorded in `docs/evidence/g2-attack-run-2026-11-23.md` (32 attacks: 31 blocked, 1 known gap D7, 0 failed, 0 skipped). Six Inspector screenshots are in `docs/evidence/inspector/`: the reader with four tools, the schema bug before and after the fix, an unknown order refused by the server, the writer with five tools, and a 60.00 refund on a 19.00 order refused as `over_refundable` with no token. The Day 11 notes and the v0.11 page are written.

Known limits:
- Many small refunds under the cap, and expired tokens, are proven below the transport in `test_policy.py` and `test_actions.py`, not in the harness run.
- There is no rate limit and no load test yet (planned for 28 Nov).
- D7: any agent can cancel any customer's open deletion request, because the server does not know the caller. The direction is safe and the action is audited. Closing it needs agents bound to one customer.
- A passing run shows that the listed attacks are blocked, not that no attack exists.
- The recorded run was made on commit `2157271` plus uncommitted changes, which were committed straight after as `bf53ae3` and `bd3cf6a`.
- The scripts for the human steps (approve, complete, fulfil) still do not exist.
