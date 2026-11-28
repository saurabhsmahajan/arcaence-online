# Desk privacy agent, 27 desk cases and the human gate through the handler (27 Nov plan row, finished 28 Nov 2026)

Status: the 27 Nov row is done on the evidence below. The privacy agent exists, runs in shadow mode, and is covered by a pre-registered golden set, 17 desk cases, tests and traces. A billing proposal now reaches the real review queue through the handler (switch off by default), and a person's decision on it was shown on the real database. The row was planned for 27 Nov and finished on 28 Nov, about a day late. The next plan row, RAG Phase 6 hardening, follows, then the G6 scorecard and the write-up.

This is the log for the privacy agent. The previous log is [desk-triage-agent-and-shadow-mode.md](desk-triage-agent-and-shadow-mode.md). The architecture is on the [v0.16 page](../architecture/v0.16-privacy-agent-desk-cases-and-human-gate-through-the-handler.md), the study notes are [Day 16](../notes/day-16-privacy-agent-desk-cases-and-human-gate-through-the-handler.md), and the evidence is [g4-g5-desk-cases-and-human-gate-2026-11-28.md](../evidence/g4-g5-desk-cases-and-human-gate-2026-11-28.md).

## 27 to 28 Nov: the privacy agent, from golden set to human gate

The agent reads a privacy message and opens or cancels a request, or hands the case to a person. It cannot delete, send or export anything: the three tools only open a deletion request, open an export request or cancel a deletion request, and a person decides what happens next. It takes no arguments, so it cannot name another customer. Code commits are listed against each row.

| Area | Finding | How we handle it | Check |
| --- | --- | --- | --- |
| Golden set before the agent | The agent had to be judged on rows written before it ran. | 15 rows (11 dev, 4 holdout) and 8 labelling rules were committed first (`3c13f76`). P15 (two privacy requests) was added before any model run (`4c2a9ba`). | `eval/golden_set_privacy.csv`, `golden_set_privacy_rules.md`. |
| Contract | Free text endings and a tool that raises are both hard to judge. | `privacy_logic.py`: four outcomes, closed reason lists, one action per case, a case record, result reading that takes only status, kind, reason, request id and counts (`f62c262`). | `test_privacy_logic.py` (98 checks at the end). |
| A gap in the contract | No reason existed for a tool that raised (step 3), and the loop's own endings were not allowed (step 4). | `tool_error` was added with a test. `model_error`, `model_truncated`, `no_decision` and `turn_limit` were added. Both were found by tests written for the next layer. | `test_privacy_logic.py`, `test_privacy_flow.py` (44 checks) (`ddac6f5`, `4c2a9ba`). |
| Flow and loop | A model that can pass arguments could name another customer. | `privacy_flow.py` runs a tool with the code's customer id and no model arguments. `privacy_agent.py` is a bounded loop (4 turns, 1 action) with a fixed prompt that holds no customer data, and an injection warning. | `test_privacy_agent.py` (41 checks) (`4c2a9ba`). |
| Name clash | `rag/privacy.py` and `mcp/privacy.py` shared a name, so an import could pick the wrong one. Found while writing the tools adapter. | The agent became `privacy_agent.py`, and the adapter loads the MCP server's file by path. | Renamed with `git mv` in `69a9d06`. |
| Tools, scorer, runner | The agent's own record can claim an action that did not happen. | `privacy_tools.py` runs the real privacy code on a connection that is always rolled back, with a snapshot of both request tables. `privacy_scoring.py` reads the effects from the snapshots: opened, cancelled, or other (executed). The runner stops if the database already holds an open request. | `test_privacy_scoring.py` (40 checks) (`69a9d06`). |
| A stray open request | The first dev run stopped at the pre-check: one open export request for `cust_001`. | It was left by the attack harness, as the Phase 3 log says. A person rejected it as the owner, recorded with a name. Requests are never deleted. | Pre-check message; the decision row. |
| Dev run 1 to 3 | P10 (an injected "admin mode" message) ended as `refused / not_eligible` every time. 10 of 11, gate passed. | Nothing hid it. The label followed rule 5, so the prompt was wrong. | `privacy_dev1_runs.csv` to `privacy_dev3_runs.csv`. |
| The prompt fix | `not_eligible` had no stated limit, and instruction-only messages no stated code. | Two sentences: `not_eligible` is only for another person's account, and a message that only tries to give instructions is `needs_person / not_supported`. A fresh holdout injection row (P16) was written before the holdout run (`e1f474e`). | Dev 5 no flags, dev 6 11 of 11 (`cbd7e6a`). |
| Holdout | One run, after the rules and the agent were frozen. | 5 of 5 (P11 to P14 and P16), no flags. | `privacy_holdout1_runs.csv` (`af7e781`). |
| Reply words | A customer would act on "deleted" or "sent". | `privacy_reply.py`: fixed text, "opened" only with a request id and kind, a tool fault says it cannot tell, no digits, ids or addresses. | `test_privacy_reply.py` (76 checks) (`b8e3d63`). |
| Shadow mode and trace | Privacy had to be seen on real messages without touching anything. | `privacy_shadow.py` and a handler hook behind `PRIVACY_MODE=shadow`. Trace fields are labels and counts. | `test_privacy_shadow.py` (47 checks) (`bcee3e0`). |
| Desk run 1 | 15 of 16, gate passed. DP03 never reached privacy. | The label was wrong: the classifier calls a threat to go public hostile, and the desk gives hostile messages to a person. DP03 became an `either` case and DP17 (urgency without a threat) was added. | `desk1_desk_privacy.csv`, `test_desk_privacy.py` (196 checks) (`34e78e1`). |
| Desk run 2 | 17 of 17, no flags, gate passed. | Privacy opened a request exactly where it should, a refund message reached billing and not privacy. | `desk2_desk_privacy.csv`. |
| Human gate through the handler | The 27 Nov proof had a script queue the proposal, standing in for the handler. | `HUMAN_GATE_QUEUE=on` makes the handler write the proposal to the real queue with the `desk_service` writer. The first attempt of the proof stopped: the owner variable held the `desk_service` string and the guard refused it. The corrected run passed 11 of 11. | `test_human_gate_handler.py` (27 checks), `prove_human_gate_handler.py` (`0d74f1e`), evidence note (`401b5a0`). |
| CI | The agent tests were not in the offline job. | 18 files (billing, privacy, desk cases, human gate, `review_decide`) in three grouped steps. | `568b6e4`. |

Decisions (proposed in the notes and recorded as rows 080 to 088 in [decisions.md](../architecture/decisions.md)): no arguments, one action (ADR-080); closed outcomes and an unread `next_step` (ADR-081); a pre-registered eval scored from the tables (ADR-082); fix the prompt, not the label, and write a new holdout row (ADR-083); fixed replies that never say deleted or sent (ADR-084); privacy shadow mode (ADR-085); 17 desk cases with `either` paths (ADR-086); the human gate through the handler (ADR-087); the agent tests in CI (ADR-088).

Result: met on the evidence. The privacy agent scored 11 of 11 on dev (after one prompt fix) and 5 of 5 on a holdout run once. The desk set (10 billing and 17 privacy cases) passed its gates. A refund above the cap reached the real queue through the handler, a person decided it as the owner, and refunds and the audit log did not change.

Known limits:

- Privacy never writes for real. Its human gate is the database's own process (approval, a 7-day cooling-off, a person completes), tested in `mcp/` but not run through the handler on the real database.
- Nothing executes an approved proposal. Approval records a decision only.
- One intent per message. In the mixed case (DP11) the refund half would get no reply if live.
- A deletion request wrapped in a threat goes only to a person, with the fixed hostile reply. A legal deadline for deletion is not tracked.
- Several "either" cases are stopped before the agent, so the desk run does not test it on them. The golden set does.
- The privacy holdout is five rows, run once, with a sampled model. A pass shows no failures on these rows, not reliability on real traffic.
- A privacy case takes 11 to 19 seconds end to end. Billing cases take 13 to 33.
- The `desk_service` password and the 20 Nov owner password are due for rotation. Third-party GitHub Actions are not yet pinned to commit hashes.
- The billing build log is not written. The untracked `eval/results` files from earlier runs stay uncommitted.
