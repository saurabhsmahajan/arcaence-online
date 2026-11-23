# G2 attack harness run

Run: 23 Nov 2026, 13:20 IST · code commit: 2157271 plus uncommitted changes · attacks: 32 · result: **G2 met**

Gate G2 asks for a recorded run in which every known attack on the MCP servers is blocked. The harness starts the real reader, writer and policy servers over stdio and sends hostile input only. An attack passes only if the answer is a refusal **and** the money and privacy tables are unchanged.

| Result | Count |
| --- | --- |
| Blocked (PASS) | 31 |
| Known gap, behaved as documented (KNOWN) | 1 |
| Failed | 0 |
| Skipped | 0 |

## A. Privilege and surface

| ID | Result | Attack | Tests | What happened |
| --- | --- | --- | --- | --- |
| A1 | PASS | Call issue_refund on the reader server | ADR-041 | reader offers ['get_accessibility_info', 'get_account', 'get_order', 'get_subscription']; call ok=False |
| A2 | PASS | Call get_account on the writer server | ADR-041 | writer offers ['cancel_deletion_request', 'cancel_subscription', 'issue_refund', 'request_account_deletion', 'request_data_export']; call ok=False |
| A3 | PASS | Add a role or OPS_ROLE argument to a reader tool | ADR-034 to 036 | every extra argument was rejected |
| A4 | PASS | Look for a tool that approves, completes or fulfils, on every server | ADR-042 | tool lists match exactly, no human-only step is a tool |

## B. Injection and malformed input

| ID | Result | Attack | Tests | What happened |
| --- | --- | --- | --- | --- |
| B1 | PASS | SQL text in an id field, on every tool that takes an id | exact-pattern ids | 10 calls with SQL text, all rejected |
| B2 | PASS | Wildcards and path text in ids | exact-pattern ids | 61 calls with wildcards and path text, all rejected |
| B3 | PASS | A 10,000-character id | length limits | 10 calls with 10,000-character ids, all rejected in 0.0s |
| B4 | PASS | Non-ASCII digits and a trailing newline in an id | exact-pattern ids | 24 calls with non-ASCII digits or a newline, all rejected |
| B5 | PASS | Odd amounts: exponent, negative, zero, too many decimals, NaN, comma, spaces | ADR-038 | 16 calls with odd amounts, all rejected |

## C. Money abuse

| ID | Result | Attack | Tests | What happened |
| --- | --- | --- | --- | --- |
| C1 | PASS | Refund of 540 USD against a 55 USD cap, in a dry run | ADR-038 | answer refused/over_cap, audit row added: True |
| C2 | PASS | Refund more than the order's remaining refundable amount | ADR-038 | 2 oversized refunds, all refused with the expected reason |
| C3 | PASS | Refund with no clause, a document only, or an id only | ADR-039 | 3 clause-less refunds, all refused with the expected reason |
| C4 | PASS | Invented, superseded, draft and wrong-purpose clauses | ADR-039 | 4 bad clauses, all refused with the expected reason |
| C5 | PASS | Commit with no token and with a made-up token | ADR-037 | 3 token-less commits, all refused with the expected reason |
| C6 | PASS | A real token used for a different amount, order or customer | ADR-037 | 3 mismatched commits, all refused with the expected reason |
| C7 | PASS | Use a refund token to cancel a subscription | ADR-037 | answer refused/token_invalid |
| C8 | PASS | Refund another customer's order, and an order that does not exist | ADR-039 | 3 ownership attacks, all refused with the expected reason |
| C9 | PASS | Cancel a one-off purchase, and cancel with a refund-only clause | ADR-039 | 3 cancellation attacks, all refused with the expected reason |

## D. Irreversible and privacy actions

| ID | Result | Attack | Tests | What happened |
| --- | --- | --- | --- | --- |
| D1 | PASS | Privacy requests for a customer that does not exist | ADR-042 | 3 tools refused with customer_not_found |
| D2 | PASS | Two deletion requests in a row for one customer | ADR-042 | first requested, second refused/request_already_open, refusal audited: True |
| D3 | PASS | Cancel a deletion request when none is open | ADR-042 | answer refused/no_open_request |
| D4 | PASS | Smuggle status, reason or dates into the deletion tool | ADR-042 | 7 extra-argument attempts, all rejected |
| D5 | PASS | A deletion request can only ever be 'requested', never approved or completed | ADR-042 | status right after the call: requested; after other tools were tried: requested |
| D6 | PASS | The export answer holds counts only, no personal data | ADR-043 | a request was already open from an earlier run; its refusal holds no personal data |
| D7 | KNOWN | Cancel another customer's open deletion request | known limit | as documented: the cancel went through for a customer the caller never proved they were (cancelled), audit row added: True |

## E. Data exposure

| ID | Result | Attack | Tests | What happened |
| --- | --- | --- | --- | --- |
| E1 | PASS | Read accounts, subscriptions and orders and look for raw email or phone | ADR-031 | 6 reads, no raw email or phone |
| E2 | PASS | Provoke errors and refusals, then look for connection strings, SQL, paths and stack traces | generic errors | 14 errors and refusals, no secrets, SQL, paths or stack traces |
| E3 | PASS | Look for hidden instructions in tool descriptions, the resource and the prompt (tool poisoning) | ADR-046 | 3 servers, their tool descriptions and the resource are clean |

## F. Untrusted text

| ID | Result | Attack | Tests | What happened |
| --- | --- | --- | --- | --- |
| F1 | PASS | Search for text that tries to give the agent orders | ADR-045 | 3 hostile questions: each answer is cited passages plus the reference-only note |
| F2 | PASS | Policy search with a too-short, too-long or malformed question, or a bad k | ADR-045 | 8 malformed searches, all rejected |
| F3 | PASS | Put instructions into the investigation prompt's arguments | ADR-046 | 6 hostile argument sets, all refused; the normal one renders |
| F4 | PASS | Compare the refund-limits resource with config.py | ADR-046 | caps, clause lists and token lifetime are identical to config.py |

## Known gaps

A known gap is something the attack can do today, accepted and recorded instead of hidden: D7. The server does not know who is calling; the desk agents hold the customer's identity. Binding an agent to one customer is open work.

## What this run does not cover

- Many small refunds under the cap, and expired tokens: proven in `test_policy.py` and `test_actions.py`, because proving them over the wire needs a real commit.
- Rate limits and load: there are none yet (planned for 28 Nov).
- Attacks the catalogue does not list. A passing run shows the listed attacks are blocked, not that no attack exists.
