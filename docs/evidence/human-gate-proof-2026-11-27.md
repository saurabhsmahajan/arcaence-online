# Human gate evidence: a refund over the limit stops and waits for a person

Run: 27 Nov 2026, 20:05 IST · code commit: 19dad59 · result: **the human gate holds (8 of 8 steps)**

The 26 Nov plan row for the billing agent ends with one done check: "A refund over the limit stops at the human gate." This note records the run that shows it, on the real database with synthetic data. It supports gates G4 and G5 but does not by itself meet them: the 20 to 30 end-to-end desk cases are not done yet (see "What this does not show").

## What was run

`rag/prove_human_gate.py --by "Saurabh"`, with two logins set in the shell for that one run and removed afterwards: the `desk_service` login (the desk's) and the owner login (a person's). Neither connection string is printed or stored.

The case is desk case D04: customer `cust_002` asks for the full 540.00 USD back on `ord_2001`, three days after purchase. The refund is inside the 7-day clause (tos_v3 3.3) but above the USD cap of 55.00, so a person must decide.

## The eight steps

| # | Step | Result |
| --- | --- | --- |
| 1 | The desk login really is `desk_service` | ok |
| 2 | The billing agent proposes the refund and does not settle it (outcome `queued`, reason `over_cap`, no refund recorded) | ok |
| 3 | The proposal is in the real queue as an open `proposed_action` | ok, item `1db066c7-fd3a-4560-8387-8ff421aefed0` |
| 4 | The desk login tries to decide the item and the database refuses (no `UPDATE` right) | ok |
| 5 | A person, on the owner login, approves it with a name and a note | ok |
| 6 | The queue shows the item approved by that person, and the proposal is exactly what the agent made | ok |
| 7 | A second decision is refused and the item stays approved (a decision is final) | ok |
| 8 | Nothing was executed: refunds and audit log are the same before and after | ok |

The proposal the agent made: tool `issue_refund`, customer `cust_002`, order `ord_2001`, amount `540.00`, clause `tos_v3 3.3`.

## The check that matters most

| | Refunds for `cust_002` (count, sum) | Audit log rows |
| --- | --- | --- |
| Before the decision | 0, 0 | 335 |
| After the approval and the refused second decision | 0, 0 | 335 |

Approving the proposal recorded a person's decision and nothing else. No refund was made and no audit row was written, because approval does not call any tool (ADR-056).

## Who can do what, as shown by this run

| Login | Add a proposal | Read it | Decide it |
| --- | --- | --- | --- |
| `desk_service` (the desk) | yes | yes | **no, refused by the database** |
| Owner (a person, through `review_decide.py`) | n/a | yes | yes, once, with a name |

The agent itself never touches the queue's decision: in shadow mode its proposal is built in memory and the script, standing in for the handler, puts it in the queue.

## What this does not show

- **The handler is not wired to the real queue yet.** In shadow mode the handler keeps the agent's proposal in memory and a stand-in queue is used. This run uses the same proposal the agent builds, but queues it by script.
- **Nothing here executes an approved refund.** That is by design: approval records a decision only. A later, separate step would have to turn an approved proposal into a refund, and it does not exist.
- **One case, one run, synthetic data.** It proves the gate holds for this path. It does not measure how often the agent proposes correctly; the billing eval and the desk cases do that.
- **The queue now holds one approved test item.** Items are never deleted, so the evidence stays.

## How to run it again

Set `DESK_SERVICE_DATABASE_URL` and `REVIEW_OWNER_DATABASE_URL` in your own shell (never in a file or in git), run `uv run python prove_human_gate.py --by "your name"` from the `rag` folder, and remove both variables. Each run adds one approved item to the queue.
