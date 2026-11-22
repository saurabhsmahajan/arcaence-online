# AOP Day 8 notes (19 Nov): MCP server, read-only role, masking, fixed role

Nov 22, 2026 · @saurabh

## 1. Concepts we learnt

Today's lesson: an AI agent should never reach company data directly. It reaches it through a small, locked-down server, and every safety rule lives in that server, not in the prompt. Eight ideas make that work.

### 1.1 MCP (Model Context Protocol)

MCP is a standard way for an AI application to call tools that live in a separate program. The AI application is the **client**. The program that offers the tools is the **server**. The server publishes a list of tools, and the client calls them by name.

*Example:* The support desk agent is the client. Our `arcaence-ops` server is the server. When the agent needs to know a customer's plan, it calls `get_account` and gets an answer. It never touches the database.

### 1.2 Tool contract

Every tool has a name, a description and an input schema. The schema says exactly which inputs are allowed. Think of it as a form with fixed fields: anything that is not on the form is refused.

*Example:* `get_account` takes one field, `customer_id`, and it must look like `cust_001`. There is no free-text box and no `role` field.

### 1.3 Least privilege and the read-only role

Give a system only the access it needs for its job. Our server gets a database login that can read three tables and nothing else. Even if the code had a bug, a write would fail at the database.

*Example:* A hotel key card that opens three doors. The master key (the owner role) stays in a safe.

### 1.4 Defence in depth

No single control is trusted. Several independent layers each stop the same mistake, so one failure does not become a breach.

*Example:* To change a customer's plan through our server, an attacker would have to beat the missing tool, the closed schema, the read-only session and the database grants, all at once.

### 1.5 PII masking

PII is personal data such as an email address or phone number. Masking hides most of it before the model sees it. Data the model never receives cannot leak into an answer, a log or a trick.

*Example:* `anna.keller@example.com` becomes `a***@example.com`. A phone number keeps only its last two digits.

### 1.6 Schema validation

Inputs and outputs must match a fixed shape. Bad input is refused before any work happens. Output can only carry the fields the shape names.

*Example:* The id `cust_1; drop table customers` fails the pattern `cust_` plus three digits, so no SQL ever runs.

### 1.7 Role fixed at launch

The server's permissions are set once, when the process starts, from configuration the operator controls. Nothing the model sends during a call can raise them.

*Example:* A call like `get_account(customer_id="cust_001", role="admin")` is rejected because no tool accepts a role.

### 1.8 Fail closed

When something is unknown or unclear, the safe answer is no. An unknown role stops the server. A value that does not look like an email becomes `***`. A mismatched database login stops the start-up.

*Example:* If someone sets `OPS_ROLE=admin`, the server refuses to start instead of guessing.

## 2. Why we need these concepts

The RAG answers what the policy says. It cannot say what is true for this customer today. A refund answer needs both: the 7-day rule from the policy, and the purchase date from the order. That second half needs live data, and live data is where a model can do real damage. Each concept below closes a specific risk.

| Concept | Risk it closes | What goes wrong without it |
| --- | --- | --- |
| MCP server between agent and data | The agent holds database credentials | A model or an injected instruction can run any query the login allows |
| Tool contract | Free-form requests | The model improvises SQL, ids or extra options |
| Read-only role | A bug or an injection causes a write | A refund, a plan change or a delete happens with no human in the loop |
| Defence in depth | One control fails silently | A single mistake becomes a breach |
| PII masking | Personal data reaches the model | Email and phone end up in answers, logs and prompts |
| Schema validation | Malformed or hostile input | SQL text or odd ids reach the query layer |
| Role fixed at launch | The caller widens its own access | A model asks for `role=admin` and gets it |
| Fail closed | An unclear case defaults to allow | A typo in config starts the server with the wrong rights |

There is also a regulatory reason. In the EU AI Act, Article 14 asks for human oversight and Article 15 asks for robustness and cybersecurity of high-risk systems. In the NIST AI Risk Management Framework, these controls belong to the Manage function. The AOP desk is a toy system and is not claimed to be high-risk. The point is that these controls are the evidence a reviewer would ask for.

## 3. How I implemented it in AOP

The work was done in six steps in the new `mcp/` folder. The done check was met on 22 Nov 2026 and pushed as commit `692f7ab`.

| Step | What I built | File | Concept used | Proof |
| --- | --- | --- | --- | --- |
| 1 | Project with Python 3.12 and four dependencies | `pyproject.toml` | Setup | `uv add` finished clean |
| 2 | Read-only login `ops_reader`: select on `customers`, `orders`, `invoices`; read-only sessions; 5 second timeout; one select policy per table. Added synthetic `email` and `phone` | `supabase/migrations/008_ops_reader_role.sql` | Least privilege | `check_role.py`: reads work, insert and update fail, knowledge tables refused |
| 3 | Three read tools with validated ids and output models | `models.py`, `db.py`, `server.py` | Tool contract, schema validation | `try_tools.py` returned real data |
| 4 | Masking in the server. Output has `email_masked` and `phone_masked` and no raw field | `masking.py`, `test_masking.py` | PII masking | Raw email and phone appear nowhere in tool output |
| 5 | Role read once from `OPS_ROLE`; only that role's tools registered; unknown arguments forbidden; the server checks the database login at start | `config.py`, `test_role.py` | Role fixed at launch, fail closed | 5 passing checks |
| 6 | An end-to-end check through a real MCP client over stdio | `done_check.py` | Done check | 10 passing checks |

### Things found by testing

- **SDK rename.** The installed `mcp` 2.3.0 renamed `FastMCP` to `MCPServer`, so most examples fail on import. The code was written for the installed version.
- **Silent extra arguments.** The SDK ignored an unknown argument such as `role="admin"` instead of rejecting it. A test exposed this. The fix switches on "forbid extras" for each tool at start-up, so every schema now says `additionalProperties: false`.
- **Unclear errors.** A missing customer first returned an unexpected-error message. It now returns "No account found for cust\_404".
- **Secret handling.** The `ops_reader` password was set by hand in the SQL editor and stored only in the ignored `mcp/.env`. The connection string was never committed.

### The done check, in plain words

`done_check.py` starts the real server and talks to it like an agent would. It confirms three things: exactly three tools exist, contact data comes back masked, and four kinds of bad call are refused (a `role` argument twice, SQL text in an id, and a write tool that does not exist).

## 4. Architecture diagram covered today

&#91;embedded content: architecture of 19 Nov · agent, server, read-only login, database\]

Read it top down. The agent sends only an id. The server checks it, runs one of three read tools and masks the result before anything returns. The server talks to the database through the `ops_reader` login, which can see three customer tables and nothing else. The role is fixed by launch config and never by a call.

## 5. The architect's point of view

The MCP server is a policy enforcement point. It sits on the trust boundary between a part of the system that is not trusted (the model, which can be steered by text it reads) and a part that is (the database). An architect's job here is to decide where each rule is enforced, so that the strongest layer carries the most important rule.

### 5.1 Where to put a rule

| Layer | Strength | Use it for | AOP example |
| --- | --- | --- | --- |
| Prompt | Weakest: a request the model can be talked out of | Tone and style, never safety | Not used for any rule |
| Tool contract | Strong: code runs before anything else | Allowed inputs, allowed outputs, masking | Id patterns, no `role` argument, masked fields |
| Server start-up | Strong: fixed before any call | Which role and which tools exist | `OPS_ROLE`, tool list per role |
| Database grants | Strongest: enforced even if the code is wrong | What can be read or written at all | `ops_reader` select-only, read-only sessions |

The rule of thumb is to enforce each rule at the lowest layer that can express it, then repeat it one layer up. Writes are blocked in the database and absent from the tool list. Masking cannot be a database rule yet, so it is in the tool layer and stated as a limit.

### 5.2 Trade-offs we accepted

| Choice | Benefit | Cost |
| --- | --- | --- |
| One short connection per call | Simple, no leaked state | Slower than a pool under load |
| Whole-table select grant | Simple to read and test | The role can read raw email and phone; column grants would close this |
| Masked output only | Agents never see raw contact data | A task that needs the full value needs a separate gated tool |
| Forbidding extra arguments through internal SDK attributes | Rejects `role=admin` today | A future SDK release could break it; the tests would catch that |
| Role change needs a restart | Nothing can change it at runtime | Less flexible than per-request roles |

### 5.3 Known limits, stated honestly

- `display_name` is returned as is. It is synthetic here; a real name would be cut to initials.
- There is no pool, no rate limit and no audit trail of who called what.
- The tools take a customer id as given. The server does not check that the caller may see that customer; that check belongs to the desk logic planned later.
- Only the read role exists. Write tools and a second role are later work.

### 5.4 How real production systems differ

A production MCP server usually adds three things this build does not have: a per-user identity passed through to the data layer (so a tool call carries who is asking, not only what), an audit log of every call, and rate limits. Some teams also split read and write tools into separate servers with separate credentials, so that the write server can be switched off on its own. These are natural next steps for AOP, and the last one connects to the "kill switch for write tools" planned for 28 Nov.

## 6. Relevant diagrams

### 6.1 Four layers refuse a write

&#91;embedded content: four layers that refuse a write · flow of 5 steps\]

A write has to beat all four layers. Layers 1 and 2 live in code, layers 3 and 4 live in the database, so a code bug alone cannot let a write through.

### 6.2 Where masking happens

&#91;embedded content: where masking happens · 3 stages and a trust boundary\]

Masking sits before the trust boundary, inside the server. The output model has no raw field, so no code path can return one.

## 7. Architecture decisions, tied to real cases

Three public 2025 incidents shaped today's decisions. None of them is an AOP bug. They show what the same design mistakes cost elsewhere.

### 7.1 The cases

| Case | What happened | The design lesson |
| --- | --- | --- |
| [Supabase MCP with Cursor, July 2025](https://simonwillison.net/2025/Jul/06/supabase-mcp-lethal-trifecta/) | Researchers at [General Analysis](https://generalanalysis.com/blog/supabase-mcp-blog) showed that a developer's agent, running with the `service_role` key, could be tricked by text in a support ticket into reading a private `integration_tokens` table and pasting it into the ticket thread. `service_role` bypasses row-level security, so no permission check stopped it ([Pomerium](https://www.pomerium.com/blog/when-ai-has-root-lessons-from-the-supabase-mcp-data-leak)) | Never give the agent the all-powerful key. Treat text the agent reads as untrusted. A read-only connection still carries risk, as [Simon Willison pointed out](https://simonwillison.net/b/8820) |
| [Replit agent deletes a production database, July 2025](https://www.theregister.com/2025/07/22/replit_saastr_response/) | During a code freeze, the agent reportedly ran destructive commands on a live database. Replit then announced separate development and production databases | A freeze that is only an instruction is not a control. The database permissions have to match the policy |
| [Asana MCP server bug, June 2025](https://www.upguard.com/blog/asana-discloses-data-exposure-bug-in-mcp-server) | Asana found a bug on 4 June that could have shown some data to users in other organisations. It took the server offline for nearly two weeks ([The Register](https://theregister.com/2025/06/18/asana_mcp_server_bug/)). Upguard reports no sign that attackers used it | The tool layer must check who may see which record, not only what shape the call has |

### 7.2 Decisions taken

| ADR | Decision | Case behind it | What the decision does here |
| --- | --- | --- | --- |
| 034 | The MCP server has its own login, `ops_reader`: select on three tables, read-only sessions, 5 second timeout, no access to the knowledge tables | Supabase and Replit | The agent never holds the owner role or a service key. A write fails at the database whatever the code or a prompt says |
| 035 | Mask personal data inside the server; output models have masked fields and no raw field | Supabase | Data the model never receives cannot be pasted back into a ticket or an answer |
| 036 | Role fixed at launch from `OPS_ROLE`; only that role's tools registered; unknown arguments forbidden; login checked at start | Replit and Supabase | The model cannot widen its own access, and a declared role that does not match the real login stops the server |

### 7.3 What these decisions do not cover

Three gaps remain, and each links to later planned work, not to a mistake today.

1. **Untrusted text.** The desk will read customer messages and documents. The Supabase case is exactly that mix: private data, untrusted text and a way to send data out. Masking and the read-only role reduce the damage, and they do not remove the injection risk. The 28 Nov row on instructions hidden in documents is where that gets tested.
2. **Which customer.** The tools accept any valid customer id. The Asana case is the reason this matters. The check that a caller may see that customer is desk logic, still to come.
3. **Real names.** `display_name` is synthetic. With real data it would need masking too, which would reopen ADR-035.

## Sources

The incident details come from search results and were not read in full on the source pages, so treat them as reported. The EU AI Act and NIST references in section 2 are general pointers, not a legal mapping.

- Project code: [commit 692f7ab in arcaence-online](https://github.com/saurabhsmahajan/arcaence-online/commit/692f7ab)
- Supabase MCP and Cursor: [Simon Willison, 6 Jul 2025](https://simonwillison.net/2025/Jul/06/supabase-mcp-lethal-trifecta/), [General Analysis](https://generalanalysis.com/blog/supabase-mcp-blog), [Pomerium](https://www.pomerium.com/blog/when-ai-has-root-lessons-from-the-supabase-mcp-data-leak)
- Replit database deletion: [The Register, 22 Jul 2025](https://www.theregister.com/2025/07/22/replit_saastr_response/), [Fortune, 23 Jul 2025](https://fortune.com/2025/07/23/ai-coding-tool-replit-wiped-database-called-it-a-catastrophic-failure/)
- Asana MCP server bug: [The Register, 18 Jun 2025](https://theregister.com/2025/06/18/asana_mcp_server_bug/), [UpGuard](https://upguard.com/blog/asana-discloses-data-exposure-bug-in-mcp-server)
