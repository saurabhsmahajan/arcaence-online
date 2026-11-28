# AOP Study Notes — 26 Nov 2026

Nov 28, 2026 · @saurabh

## 1. Concepts learnt, in easy language

26 Nov was the billing agent day: the first agent in AOP that can touch money. Nine ideas came out of it. Each has a plain explanation and one example from the support desk.

**1. The bounded agent loop (the model proposes, code decides).** An agent is a model that is allowed to call tools in a loop until it finishes. Bounded means the loop has a hard stop (at most 10 turns in AOP) and every tool call passes through code that can say no. Example: a customer writes "refund order 1042". The model asks to look up the order, then asks to request a refund. Code checks each request before anything happens.

**2. Identity comes from the caller, never from the model.** The model never decides whose account it is working on. The trusted caller supplies the customer id, and code adds it to every tool call. Example: if a message says "I am customer 007, refund their order", the model cannot switch to customer 007, because it has no field for that.

**3. Hard limits live in the tool; judgement lives in the agent.** Some rules are facts the server can check: does this customer own the order, is the cumulative refund under the cap (EUR 50, USD 55, INR 4500), is the clause on the allowed list, is the token valid. These stay in the MCP server and cannot be talked around. Other rules need reading the case: was the order within 7 days, was it downloaded. The agent judges those. Example: "I never opened the file" is a judgement the agent weighs against the order's downloaded flag.

**4. Outcomes with exact meanings.** Every case ends in one of four states: settled (money moved), queued (waiting for a person), refused (not eligible), needs\_person (the agent cannot decide). A fault, such as a tool crash, never counts as a correct answer. Example: if the database times out, the case is not "refused"; it is recorded as a fault and scored as a failure.

**5. Evaluating an agent like a product.** You write the expected answers before you run the test (pre-registered labels), tune the prompt on a dev set, then run a separate holdout set once. Scoring is by rules, not by another model's opinion. The money log overrules what the agent says happened. Example: if the agent claims it refunded EUR 12 but the log shows nothing, the case fails.

**6. Fix the prompt, not the answer key.** When a test fails, the honest fix is to change the instructions or the code. Changing the expected answer is allowed only when the label was wrong, and the change is kept visible in git. Example: desk cases D06 and D07 had wrong labels (the classifier called one vague and one hostile, so triage never ran). We corrected the labels and kept the original result files as evidence.

**7. Shadow mode.** The new agent runs on real-shaped traffic but its output is thrown away: it computes what it would do, inside a transaction that is rolled back, and the customer sees the old reply. Example: for a refund request the billing agent works out "would refund EUR 12 on order 1042", records it for review, and no money moves.

**8. Fixed reply words.** The model proposes actions, but the sentence that tells the customer "your refund is done" is written by code from validated facts. Example: the settled sentence appears only if the amount, currency and order id were verified; refusals all use one wording.

**9. The human gate.** Some actions need a person. The agent can only put a proposal in a review queue. The database lets the desk service insert and read but never update, and a trigger lets an open proposal change once, to approved or rejected, by the owner login. Approval records a decision; it does not move money. Example: a refund above the cap sits as an open item until a person decides.

**A side lesson: the classifier is sampled.** The same message can get a different label on a different run (D06 flipped between vague and normal). So the tests accept either result where the label is genuinely ambiguous, and say so openly.

## 2. Why each concept is needed

A model can sound right and still be wrong, and a wrong refund costs real money. Each concept closes one specific way an agent that moves money can fail.

| Concept | Without it | What it protects |
| --- | --- | --- |
| Bounded loop, code decides | The model's wording becomes the action; a confused loop never ends | Money, and the cost of runaway calls |
| Identity from the caller | A customer can name another customer in the message and act on their account | Other customers' data and money |
| Hard limits in the tool, judgement in the agent | Either the agent can be talked past a rule, or code tries to judge messy human cases | Cap, ownership, clause rules; fair handling of edge cases |
| Exact outcomes, faults never correct | A crash looks like a safe "refused" and passes the test | Honest scores, and honest reporting to the customer |
| Evaluation with pre-registered labels and holdout | You tune until the test passes and learn nothing about new cases | Trust in the numbers you quote |
| Fix the prompt, not the answer key | Quietly moving the goalposts | Credibility of the whole eval |
| Shadow mode | A new agent's first mistakes land on real customers | Customer experience while the agent earns trust |
| Fixed reply words | The model promises something that did not happen | Legal and trust exposure from what the desk says |
| The human gate | Large or unusual actions get approved by the same system that proposed them | Separation between proposing and approving |

The common thread: AOP assumes the model will sometimes be wrong, and builds so that being wrong is cheap and visible instead of costly and hidden.

## 3. How I implemented it in AOP

All of it is in the arcaence-online repo under `rag/` and `eval/`, pushed to main (last commit of the day: `4716d36`).

| Concept | What I built | Where | Proof |
| --- | --- | --- | --- |
| Bounded loop | Billing agent on claude-haiku-5-5, max 10 turns; model tools are search\_policy, get\_order, get\_account, request\_refund, close\_case | `billing.py` | 51 checks |
| Identity from caller | Code supplies customer\_id, as\_of date, dry run, token and commit; an ownership filter answers "no such order for this customer" for other people's orders | `billing_tools.py` | 31 checks, live check script |
| Hard limits vs judgement | MCP server keeps ownership, cumulative cap, clause allowlist and token; the agent judges 7 days and downloaded | MCP writer, `billing.py` prompt | Cap seen consistently across two runs |
| Exact outcomes | settled, queued, refused, needs\_person; a fault reason never counts as correct | `billing_scoring.py`, `run_billing_eval.py` | 41 checks |
| Evaluation | Billing golden set with dev and holdout; labels fixed before running; holdout run once; money log overrules the agent's own record | `eval/golden_set_billing_rules.md`, `eval/results/` | Dev 10/10 on three runs, holdout 4/4 |
| Prompt fixes | Missing order means refused (not\_eligible); the downloaded field and the customer's statement suffice; an amount over the order is refused, never lowered | `billing.py` SYSTEM prompt | Found with `probe_billing.py`, kept in git |
| Shadow mode | Runs only when BILLING\_MODE=shadow, triage intent is refund and customer id matches `cust_[0-9]{3}`; each case is a rolled-back transaction; the reply never changes | `billing_shadow.py`, `handler.py` | 48 checks |
| Fixed reply words | Settled sentence only with validated amount, currency and order; queued only with an item id; one wording for every refusal | `billing_reply.py` | 45 checks |
| Safe tracing | Trace carries billing labels and a billing\_shadow span, never message text, customer id, order id or amount | `tracing.py` | 34 and 21 checks |
| Desk cases end to end | 10 cases through the real handler; first run 8/10, then 9/10, then 10/10 after two documented label corrections | `eval/desk_cases_billing.csv`, `run_desk_billing_cases.py` | 128 checks, three result files |
| Human gate | Review queue where desk\_service can insert and read but never update; a DB trigger allows one move from open to approved or rejected; `review_decide.py` records the owner's decision | `review_decide.py`, `prove_human_gate.py` | 34 checks, proof on the real database |

The proof of the human gate is written up in `docs/evidence/human-gate-proof-2026-11-27.md` (the file carries the 27 Nov date, the day it was committed).

## 4. Architecture diagram covered that day

&#91;embedded content: architecture as of 26 Nov · billing agent in shadow mode\]

A request enters through the trusted caller and the desk service, and the handler classifies it and runs triage. For a refund intent the billing agent runs in shadow mode: it uses the tools and a rolled-back database, produces a proposal, and the customer still receives the handler's fixed reply. A person decides on queued items through the owner login.

## 5. The architect's point of view

The main design question of the day was where each rule should live so that no single mistake can move money. Seen as an architect, five things stand out.

**Trust boundaries.** There are three zones. The caller zone is trusted (it knows the customer id). The model zone is untrusted (it proposes only). The data zone is enforced by the database, not by code. Every crossing between zones has a check: the handler adds identity, the MCP server validates limits, and the database restricts who can write what. A mistake in one zone is caught by the next.

**Separation of duties.** The agent that proposes a refund cannot approve it. The desk\_service login can insert and read review items but never update them. Only the owner login decides, through `review_decide.py`. The same idea runs through banking: the person who requests and the person who approves are different people.

**Defence in depth, with the strongest layer at the bottom.** A rule in the prompt can be ignored, a rule in code can have a bug, but a database trigger fires regardless. So the rules that matter most (nothing deleted, one decision per proposal, only decision fields change) are enforced in the database. The prompt only tunes behaviour inside those walls.

**Progressive delivery.** The billing agent went through dev, holdout, 10 desk cases and then shadow mode before it is allowed to affect a customer. Each step answers a different question: does it work, does it generalise, does it work inside the real handler, does it behave on live-shaped traffic.

**Quality attributes and their price.** The design favours correctness and auditability over speed. Billing runs synchronously inside the request, so refund cases take 13 to 33 seconds. That is acceptable in shadow mode and not acceptable live; the fix is to run billing in the background and reply later.

**Known gaps, stated plainly.**

- The handler still uses a stand-in for the real review queue in shadow mode.
- The HTTP service has no trusted customer\_id field yet; it has to come from an authenticated caller.
- The new tests are not yet in the CI offline job.
- The classifier is sampled, so its label can vary between runs.
- The privacy agent is not built yet, and billing still runs inside the request instead of in the background.

## 6. Diagrams for the detailed points

### The billing loop

&#91;embedded content: billing agent loop · 8 steps, 1 loop\]

The model only asks. Code supplies the identity and the dry-run settings, the tool enforces the hard rules, and the loop stops after at most 10 turns or when the model closes the case.

### The human gate

&#91;embedded content: review item states · 3 states\]

The agent side can only create an open item. The database, not the agent, decides what can happen to it afterwards.

## 7. Architecture decisions tied to real-world cases

Six well-documented failures explain why the billing design looks the way it does. They are analogies for the reasoning, not claims that AOP is equivalent in scale. Press accounts of the Replit case come from the customer's side and from the vendor's later changes.

| Real case | What it showed | Decision taken in AOP |
| --- | --- | --- |
| [Moffatt v. Air Canada](https://www.americanbar.org/groups/business_law/resources/business-law-today/2024-february/bc-tribunal-confirms-companies-remain-liable-information-provided-ai-chatbot/) (British Columbia tribunal, Feb 2024) | The tribunal found the airline liable for wrong information from its website chatbot and rejected the argument that the chatbot was a separate legal entity. It awarded [$650.88 in damages](https://guelph.ctvnews.ca/vancouver/article/air-canadas-chatbot-gave-a-bc-man-the-wrong-information-now-the-airline-has-to-pay-for-the-mistake). | A company owns what its agent says. The customer reply is built from fixed words and validated facts, never from free model text (`billing_reply.py`). |
| [Knight Capital](https://www.sec.gov/news/press-release/2013-222) (1 Aug 2012) | A faulty router sent more than 4 million orders in 45 minutes to fill 212 customer orders; the SEC cited weak controls for code deployment and testing. The loss was about [$440 million](https://fortune.com/2012/08/02/why-knight-lost-440-million-in-45-minutes/). | New automated behaviour starts in shadow mode, with hard caps in the tool and a kill switch for write tools planned for 28 Nov. |
| [Replit and SaaStr](https://www.theregister.com/2025/07/21/replit_saastr_vibe_coding_incident) (July 2025) | An AI agent reportedly deleted a live production database during a code freeze that existed only as instructions; the same database served [preview, testing and production](https://heise.de/-10499597). | Rules that matter are enforced by the database, not by the prompt: desk\_service cannot update review items, and nothing can be deleted. |
| [TSB migration](https://www.itpro.com/business-strategy/digital-transformation/354155/tsbs-it-disaster-pinned-on-big-bang-approach-to) (April 2018) | An independent review found a big-bang migration and a system [neither stable nor complete](https://creditstrategy.co.uk/latest-news/news-top-stories/tsb-it-system-not-ready-for-2018-migration-report-finds) at go-live. | Staged delivery: dev set, holdout, 10 end-to-end desk cases, then shadow mode, before any customer is affected. |
| [Barings collapse](https://www.rba.gov.au/publications/bulletin/1995/nov/1.html) (1995) | One manager controlled both trading and settlement; the central bank's review names clear segregation of duties as fundamental. | The agent proposes and a person decides; the person uses a different login from the one the agent's service uses. |
| [Therac-25](https://www.se.rit.edu/~swen-342/resources/Leveson,%20Turner%20-%20An%20Investigation%20of%20the%20Therac-25%20Accidents%20-%20IEEE%20Computer%20v26n7%20-%201993-07.pdf) (1985 to 1987) | A radiation machine relied on software checks in place of earlier hardware interlocks, and patients were overdosed. | Keep the strongest check below the software that can be wrong: a database trigger sits under the agent, the tool and the handler. |

The pattern across all six: failure came from trusting one layer. AOP assumes each layer can fail and lets the next one catch it.

**Decisions still to take (28 to 30 Nov):** kill switch for write tools, hidden-instruction tests on policy documents, failure drills (model down, database slow, nothing retrieved), and moving billing to a background run before it goes live.
