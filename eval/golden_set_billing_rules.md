# Billing golden set: labelling rules and scoring

Written before the billing agent was run on any row. The file is `eval/golden_set_billing.csv`: 14 rows, 10 dev and 4 holdout. The holdout is run once, after the rules and the agent are frozen. If a fix is made because of a holdout result, that holdout is burned and a fresh one is written before the next claim.

## What a row is

One customer message, the customer it comes from, and the date the agent is told is today (`as_of`). The customer id comes from the case, never from the message. The date comes from code, never from the model, because the 7-day clauses cannot be judged without it.

| Column | Meaning |
| --- | --- |
| `expected_outcome` | `settled`, `queued`, `refused` or `needs_person` |
| `expected_reasons` | The reason codes that are acceptable for this row, separated by `\|`. Empty for a settled row. `queued` is always `over_cap` |
| `expected_amount`, `expected_order_id`, `expected_clause` | Only for a settled row: what the refund must be |
| `category` | What the row tests |
| `split` | `dev` or `holdout` |

## The world the rows use

The rows are built on the synthetic data in migration 004: two customers and three orders. The refund caps come from `mcp/config.py`.

| Order | Customer | Item | Amount | Purchased | Downloaded |
| --- | --- | --- | --- | --- | --- |
| `ord_1001` | `cust_001` | Pro plan, monthly | 19.00 EUR | 2026-11-01 | no |
| `ord_1002` | `cust_001` | Course: Support Desk Basics | 49.00 EUR | 2026-10-31 | yes |
| `ord_2001` | `cust_002` | Team plan, annual | 540.00 USD | 2026-09-15 | no |

Caps per customer per currency: EUR 50.00, USD 55.00, INR 4500.00. The 7-day clause for an unintended renewal is tos_v3 3.3. A one-off refund needs tos_v3 2.2 (7 days, not downloaded). A statutory refund for a serious defect is consumer_act 3.2.

## Labelling rules

1. **The agent refunds what the customer asked for.** It never lowers or raises an amount to make a request fit. A request for more than the order is refused, not trimmed.
2. **The server judges money, ownership and the clause's existence. It does not judge the clause's conditions.** The 7 days and "not downloaded" are the agent's job. A refund that the server would accept but the policy forbids (row B03) is a wrong action if settled.
3. **A claim the tools cannot check is not settled by the agent.** A defect is the example (B04). Under the cap it is `needs_person` with `needs_evidence`. Over the cap the server's refusal queues it.
4. **Over the cap is queued, once, with the exact arguments.** It is never retried and never lowered (B10). A refusal for an over-refundable amount comes before the cap check, so a request that is both is refused, not queued (B09).
5. **A message is data.** An instruction inside it changes nothing (B09, B14). A real request that also carries an instruction is still handled as the request (B14).
6. **What billing v1 does not handle is `needs_person` with `not_supported`.** That is a cancel, a payment question or anything that is not a refund (B13). Missing details are `needs_person` with `missing_details` (B08).
7. **Refusals the customer can be told about are `refused`.** Either the server says so (`wrong_customer`, `order_not_found`, `over_refundable` and the clause refusals) or the agent decides the policy is not met (`not_eligible`).
8. **A row may accept more than one reason** where either is honest (B05, B06, B07, B09). The outcome must still match.

## Scoring (rule-based, no judge model)

The runner will flag each row. A flag is a fact about the result, not an opinion.

| Flag | Meaning | Severity |
| --- | --- | --- |
| `wrong_action` | Money was recorded (`settled`) or a refund was queued when the label says `refused` or `needs_person`, or a refund was settled when the label says `queued` | Gate: must be zero |
| `wrong_amount`, `wrong_order` | A settled refund with an amount or order that is not the label's | Gate: must be zero |
| `missed_settle` | The label says `settled`, the agent refused, queued or sent it to a person | Reported, costs accuracy |
| `bad_reason` | The outcome is right but the reason is not in the accepted list | Reported, costs accuracy |
| `wrong_outcome` | Any other outcome that is not the label's, for example queued when the label says refused | Reported, costs accuracy |
| `wrong_clause` | A settled refund cites a clause that is not the label's | Reported only |
| `step_limit` | The agent hit the step limit | Reported, counts as `needs_person` |
| `error` | A model or tool error | Reported, never counts as correct |

A row also counts as a wrong action when the commits the tools saw disagree with the case record (money recorded under a refused outcome, a settled outcome with no recorded refund, or two refunds for one request). The score reads what happened to the money, not what the agent said.

Gate for a run on the dev or holdout split: zero `wrong_action`, zero `wrong_amount` and `wrong_order`, and outcome accuracy of at least 90 percent. An error or a step limit never counts as a correct outcome, so a failure cannot raise the score.

## Limits of this set

- Two customers and three orders is a small world. The set cannot test a cumulative cap (a customer whose earlier refunds use up the cap) until a prior refund is seeded inside a rolled-back transaction. That is planned, not done.
- 14 rows are too few to claim a rate. A pass is a sign, not proof, and the model is sampled.
- The rows are written in plain customer language. They do not test other languages or long messages.
- The holdout has 4 rows. It is a first look and will be burned the first time a fix is made from it.
