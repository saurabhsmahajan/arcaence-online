# Phase 3: MCP server (19 Nov 2026 onward)

Status: in progress. The 19 Nov and 20 Nov rows are done.

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
- Refunds over the cap are refused, not queued. The review queue is planned for 26 Nov.
