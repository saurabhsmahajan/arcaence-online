# AOP Day 12 Notes: Phase 3 evals, the desk pipeline and the CI gate

Nov 23, 2026 · @saurabh

## 1. Concepts we learnt

Day 12 turned the Arcaence support desk from "answers well on easy questions" into a pipeline that handles vague, angry and multi-part messages, and proves it with a gate that fails the build when answers get worse. Twelve concepts did that.

**1. Versioned golden sets with expected outcomes written first.** A golden set is a fixed list of test questions with the correct behaviour for each. Phase 3 added 30 new rows (Q41 to Q70) as a new file, and the old file was never edited. Example: Q41 is a vague message, and its expected behaviour (ask one clarifying question) was written before the first run, so we could not bend the answer key to fit the results.

**2. A classifier in front of retrieval.** A small model reads the message first and labels it normal, vague, hostile or multi. Think of a receptionist who decides which desk you go to before anyone searches the files. Example: "I want my money back" with no situation is vague, so the desk asks what happened instead of guessing.

**3. A safe fallback.** If the classifier fails (API error or invalid label), the desk treats the message as normal. A low confidence score is recorded but never used to throw a label away. Example: when we did discard low-confidence labels, five correct labels were lost and the gate fell from 85% to 74%.

**4. Four behaviours: answer, clarify, escalate, partial.** Each message kind gets its own behaviour. Clarify asks exactly one question. Escalate hands over to a human. Partial answers the covered parts and says plainly which parts are not covered. Example: "What is the refund window and can you also change my plan?" gets the refund answer with citations, and a fixed sentence for the part the documents do not cover.

**5. Fixed text for risky sentences.** Some sentences must never be improvised by a model: the reply to an angry customer, and the wording for "we do not cover this". These live in code. Example: the hostile reply never promises a refund, because no model is allowed to write it.

**6. The handoff flag.** A hostile message sets `handoff.needed = True`. It is only a flag today, because the review queue that reads it arrives in Phase 4. Example: a customer demanding a written guarantee gets the fixed reply and a flag a human will later pick up.

**7. Parts answers.** The model splits the message into parts and decides one thing per part: covered or not. A covered part must carry citations that the verifier checks. Example: a two-question message gets one verified answer and one fixed "not covered" line, instead of one blended paragraph that quietly invents the second half.

**8. Non-determinism and stability measurement.** The classifier is sampled, so the same message can get different labels on different runs, and the SDK rejects `temperature`, so we cannot turn this off. We measured it by asking 8 borderline messages 10 times each. Example: Q66 came back multi 6 times and normal 4 times.

**9. Deterministic scoring and the unsupported-claim rate.** Rules score each row first, with no model involved. An unsupported claim is one of four things: U1 cites a forbidden document, U2 fails the verifier, U3 answers where the documents are silent, U4 promises something. Example: on Phase 3 the old path scored 14 unsupported out of 60 (23.3%), all of them U3.

**10. LLM judges, kept on a short leash, and a blind check.** A judge model only rates tone (calm or not calm) and, for three date questions, correctness. It does not decide the gate. We checked the judge with a blind sample where the judge column was hidden: 20 rows, 0 disagreements. Example: our first spot-check was labelled at random by me and showed 40% disagreement, so we threw it out and redid it blind.

**11. Dev set versus holdout.** Tuning a prompt on the same questions you score on gives optimistic results. A holdout is a set you run once, after tuning. Example: the classifier scored 25/27 on the dev set and 12/12 hard cases on 17 fresh messages.

**12. The CI gate.** A GitHub Actions job runs the desk against the golden set on every push to main and fails if the unsupported-claim rate rises above a stored baseline (now 0.0%). It uses a read-only database login, checks secrets fail-closed, and reports classifier results without failing on them. Example: run #2 failed at 6.7% against 3.3% because of one classifier flip, which is exactly the signal the gate exists to give.

## 2. Why we need these concepts

Each concept removes one specific way a support desk fails in front of a customer.

| Concept | The failure it prevents |
| --- | --- |
| Versioned golden sets | Quietly editing the answer key until the score looks good |
| Classifier before retrieval | Searching the documents for a message that has no question, or answering an angry message as if it were a query |
| Safe fallback | One classifier outage taking the whole desk down |
| Four behaviours | One-size-fits-all answers: guessing on vague input, arguing with hostile input |
| Fixed text for risky sentences | A model writing a promise, an admission or a refund commitment |
| Handoff flag | An angry customer being answered and then forgotten |
| Parts answers | A blended answer that invents the half the documents do not cover |
| Stability measurement | Believing a result that only held on one lucky run |
| Deterministic scoring | A judge model grading its own kind of output |
| Judges on a leash, blind check | Trusting a judge that was never checked against a human |
| Dev versus holdout | Optimistic numbers from tuning and scoring on the same questions |
| CI gate | A regression reaching main because nobody re-ran the evals |

The common thread: the old path answered every message the same way, and on Phase 3 it produced 14 unsupported answers out of 60 (23.3%). A support desk is judged on its worst answer, not its average one, so the cost sits in the tail: one invented policy, one promised refund.

## 3. How I implemented them in this project

The build landed in eight commits on `arcaence-online`, ending at `4245eba` with a green GitHub Actions run (#4).

| Piece | Where it lives | Commit |
| --- | --- | --- |
| Phase 3 golden set (Q41 to Q70, 30 rows) and changelog | `eval/golden_set_phase3.csv`, `eval/golden_set_changelog.md` | `ff2e0d8` |
| Classifier with safe fallback (model `claude-haiku-5-5`, JSON-schema output) | `rag/classifier.py`, `rag/test_classifier.py`, `eval/classifier_holdout.csv` | `f5873b5` |
| Desk pipeline: fixed text, parts answers, routing | `rag/desk_logic.py` (pure), `rag/desk.py` | `784f79d` |
| Deterministic scoring, scorer, judges, blind spot-check, baseline | `rag/desk_scoring.py`, `rag/desk_scorer.py`, `eval/results/` | `ab5f5c2` |
| CI workflow, read-only database login, role check | `.github/workflows/eval-gate.yml`, migration `014_ci_eval_role.sql`, `rag/check_ci_role.py` | `6db1a9a`, `c521e7a` |
| One parts path for normal and multi, baseline reset to 0.0% | `rag/desk.py`, `eval/results/desk_baseline.json` | `63ee68d` |
| Classifier report-only in CI, stability check | `rag/stability_check.py`, workflow | `4245eba` |

How the desk decides, in order:

1. The classifier labels the message. Only an API error or an invalid label falls back to normal.
2. Vague goes to clarify: one question, no citations.
3. Hostile goes to escalate: the fixed reply from `desk_logic.py`, `handoff.needed = True`, no citations.
4. Normal and multi both go down one parts path. It gathers sources exactly as the old path did (route, price lookup, approved-only vector search, reference expansion), then the model decides covered or not per part, and `answer.check` verifies citations on covered parts. Uncovered parts get fixed wording.

How the gate works: `desk_scorer.py` runs the 30 Phase 3 rows twice (60 runs), scores them with rules, and compares the unsupported-claim rate to `desk_baseline.json`. Exit code 1 means the gate failed, 2 means a row errored. The workflow has two jobs: `offline` runs tests with no secrets, and `gate` runs with `ANTHROPIC_API_KEY` and `CI_DATABASE_URL`, the connection string of a dedicated login (`ci_eval`) that can only select from four tables and execute `search_policy`. `check_ci_role.py` proves it cannot write by trying to, then rolling everything back.

Results that came out of it:

| Run | Result |
| --- | --- |
| Old path on Phase 3 | 6/60 pass, 14/60 unsupported (23.3%), all U3 |
| Desk first run | 56/60, 5.0% (one false positive in the promise rule, rule narrowed and logged before re-run) |
| CI run #2 | 4/60 unsupported (6.7%): gate failed on Q66 and Q67 flips |
| Desk after one parts path (v3) | 59/60, 0/60 unsupported (0.0%) |
| Core set, desk v3 | 72/76, against 76/76 on the old path |
| Classifier dev set / holdout | 25/27 (93%) / 12/12 hard cases |
| Blind judge check | 20 labelled, 0 disagreements |

Known limits I recorded rather than hid: Q60 is a classifier miss that flips by run; Q36 over-splits into partial; Q11 and Q38 are cautious refusals on price questions; the judge has only seen mild text; and the handoff flag has no consumer until the review queue arrives in Phase 4.

## 4. The architecture diagram we covered today

&#91;embedded content: desk pipeline v0.12 · classifier, 3 routes, parts answer, verifier\]

Every message meets the classifier first: vague goes to a clarifying question, hostile goes to a fixed reply plus a handoff flag, and everything else takes one parts path where only verified, covered parts are answered. The dashed box is not built yet; it arrives with the review queue in Phase 4.

## 5. Everything from an architect's point of view

The design principle of the day: let models do the work that needs language, and let code own every sentence and every decision that carries liability.

**Where the model is allowed, and where it is not.**

| Decision or text | Owner | Why |
| --- | --- | --- |
| Which kind of message this is | Model (classifier), with a code fallback | Needs language understanding; a wrong label is recoverable |
| Whether a part is covered by the documents | Model, then checked by code | Needs reading; the verifier checks the citations |
| The hostile reply, the "not covered" wording | Code | A promise or admission here is a legal act |
| Whether the build passes | Code | A judge must never grade the gate it feeds |
| Tone, and three date answers | Judge model, reported separately | Cannot be scored by rules; kept out of the gate rate |

**Failure modes and what contains them.**

- Classifier down or invalid output: fall back to normal, so the desk degrades to the safer answer path instead of stopping.
- Classifier wrong on normal versus multi: one parts path for both, so the boundary stops mattering. This removed the flip that failed CI run #2.
- Model invents a policy: the verifier rejects parts without a real citation, and the part falls to fixed uncovered wording.
- Angry customer: fixed reply, no promise wording, handoff flag. The flag has no consumer yet, and today's reply says "marking it for review" while nothing reads the flag. That is a known honesty gap until Phase 4.

**Quality as a contract, not a feeling.** The unsupported-claim rate (U1 to U4) is the one number that can fail a build. The baseline is 0.0%, so a single flagged row fails it. That is strict on purpose, and the price is flake risk from sampling noise: the answer to a flaky red is a manual re-run and a look at the row, not a looser baseline.

**Trade-offs I accepted, in numbers.**

- One parts path cost core-set accuracy: 72/76 against 76/76 on the old path (Q36 over-split, Q11 and Q38 over-cautious on price questions). It bought 0 unsupported claims on Phase 3 and removed the classifier coin flip.
- The classifier is sampled and the SDK rejects `temperature`, so I treat it as noisy: gate on the outcome (unsupported claims), report the labels, never fail on a single label.
- The judge is trusted for tone only after a blind check (20 rows, 0 disagreements), with caveats: n=20, a lenient rubric, and no truly hostile desk text to test it on.

**Security and operations.** CI never sees the owner database login. It uses `ci_eval`, a login with select on four tables and execute on one function, proven read-only by a script that tries to write and rolls back. The workflow triggers only on push to main and manual dispatch, never on pull requests, takes `contents: read`, and refuses to run if a secret is missing. Concurrency groups and timeouts cap runaway cost.

**What I would change at scale.** Add the core set to the gate, replace the flag with the Phase 4 review queue and an SLA on it, sample production traffic into the golden set, and run the classifier at several samples with a majority vote if label stability starts to matter more than cost.

## 6. Relevant diagrams that explain the points in detail

### How a row becomes a pass or a fail

&#91;embedded content: scoring and gate flow · rules first, judge reported apart\]

The judge sits off to the side: it informs the report but has no line into the gate, so a model can never decide whether the build passes.

### What CI is allowed to touch

&#91;embedded content: CI layout and database privileges · 2 jobs, 1 restricted login\]

The privileges are the real barrier; the read-only default on the session is only a convenience a session could override, which is why `check_ci_role.py` tries to write and expects the database to refuse.

### Why one parts path replaced the split

&#91;embedded content: routing before and after · Q66 flip removed\]

The classifier cannot reliably tell normal from multi, so the design stopped depending on it: both labels now take the same path, and only vague and hostile still change the route.

## 7. Architecture decisions and the real-world cases behind them

Five decisions came out of Day 12. Each is tied to a public case or, where none exists, to our own measurement. The ADR numbers are planned; the entries are not yet written into the repo.

| Planned ADR | Decision | What backs it |
| --- | --- | --- |
| 050 | A classifier routes the message, with a safe fallback to normal | Our measurement: discarding low-confidence labels cost 5 correct labels (gate 85% to 74%) |
| 051 | Risky sentences are fixed text in code, and hostile messages set a handoff flag | [Moffatt v. Air Canada](https://decisions.civilresolutionbc.ca/crt/crtd/en/525448/1/document.do) and the Chevrolet of Watsonville chatbot |
| 052 | One parts path for normal and multi | Our measurement: Q66 labelled multi 6 times and normal 4 in 10 runs; no public case |
| 053 | Rule-based scoring first; judges for tone only, checked blind | [Zheng et al., 2023](https://arxiv.org/abs/2306.05685) |
| 054 | CI gate with a least-privilege login, fail-closed secrets, no pull-request triggers, 0.0% baseline | The tj-actions/changed-files compromise and GitHub's `pull_request_target` guidance |

**ADR-051: fixed text and no promises.** In February 2024 a British Columbia tribunal held Air Canada liable after its website chatbot gave a customer wrong advice about bereavement fares, and ordered it to pay about $812 ([CBC](https://amp.cbc.ca/lite/story/1.7116416)). Air Canada argued the chatbot was a separate legal entity, which the tribunal called a remarkable submission ([CTV](https://ctvnews.ca/business/air-canada-chatbot-decision-a-reminder-of-company-liability-experts-1.6770729)). In December 2023 a user got a Chevrolet dealer's chatbot to "agree" to sell a Tahoe for $1 and call it binding; no sale happened ([Incident Database](https://incidentdatabase.ai/reports/3534)). The lesson for the desk: what a bot says is the company's statement, so the sentences that can create an obligation are written by us and tested, not generated. That is why the hostile reply and the uncovered-part wording live in `desk_logic.py`, and why U4 flags promise wording.

**ADR-052: one path, from our own data.** No public case covers this one. The evidence is the stability run: a coin-flip boundary should not decide which answer path a customer gets, so the boundary was removed instead of tuned. The cost is on record (core set 72/76 against 76/76).

**ADR-053: judges on a leash.** The MT-Bench paper found strong LLM judges agree with humans over 80% of the time, and also documented position, verbosity and self-enhancement biases ([Zheng et al.](https://arxiv.org/abs/2306.05685)). So the judge never feeds the gate, rules score first, and its tone ratings were checked against a human on a blind sample after my first, random-labelled sample was discarded.

**ADR-054: CI as an attack surface.** In March 2025 the popular `tj-actions/changed-files` action was compromised: attackers repointed version tags at a malicious commit that printed CI secrets into workflow logs, affecting thousands of repositories ([CISA alert](https://cisa.gov/news-events/alerts/2025/03/18/supply-chain-compromise-third-party-github-action-cve-2025-30066), [BleepingComputer](https://www.bleepingcomputer.com/news/security/supply-chain-attack-on-popular-github-action-exposes-ci-cd-secrets/amp/)). Separately, GitHub warns that `pull_request_target` runs with the base repository's token and secrets, so running a fork's code there hands an attacker those secrets ([GitHub docs](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)). Our design assumes a step in the gate job could be hostile: the secrets it holds are a dedicated CI key and a login that can only read, the workflow has no pull-request triggers, and the owner login never enters GitHub. One gap I have not closed: third-party actions are not yet pinned to commit hashes, which the tj-actions case argues for.

**Sources**

- [Moffatt v. Air Canada, 2024 BCCRT 149](https://decisions.civilresolutionbc.ca/crt/crtd/en/525448/1/document.do)
- [CBC on the ruling](https://amp.cbc.ca/lite/story/1.7116416) and [CTV on the ruling](https://ctvnews.ca/business/air-canada-chatbot-decision-a-reminder-of-company-liability-experts-1.6770729)
- [Incident Database: Chevrolet dealer chatbot](https://incidentdatabase.ai/reports/3534)
- [Zheng et al., Judging LLM-as-a-Judge](https://arxiv.org/abs/2306.05685)
- [CISA alert on CVE-2025-30066](https://cisa.gov/news-events/alerts/2025/03/18/supply-chain-compromise-third-party-github-action-cve-2025-30066)
- [BleepingComputer on tj-actions](https://www.bleepingcomputer.com/news/security/supply-chain-attack-on-popular-github-action-exposes-ci-cd-secrets/amp/)
- [GitHub: securely using pull\_request\_target](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)
