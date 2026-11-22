# Phase 3: MCP server (19 Nov 2026 onward)

Status: in progress. The 19 Nov row is done.

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
