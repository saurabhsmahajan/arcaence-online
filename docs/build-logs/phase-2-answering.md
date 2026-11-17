# Phase 2: structured answers, failure diagnosis and access (16 to 18 Nov 2026)

Status: in progress. The 16 and 17 Nov rows are done. The 18 Nov row and gate G1 are not started.

## 16 Nov: structured answers, verifier gate and retry

The answer step now returns a schema-shaped answer, the same verifier gates it, a failed answer gets a bounded retry with the reasons fed back, and an answer that cannot be verified becomes a refusal. Findings:

| Area | Finding | How we handle it | Golden-set trap |
| --- | --- | --- | --- |
| Answer format | Free text with brackets and a `NOT_FOUND` string has no guaranteed shape. | JSON schema in `output_config.format`: `answer`, `citations`, `refused`, `refusal_reason`. Support on claude-haiku-5-5 was confirmed with a smoke test, not assumed. It cannot be combined with the API's own citations or with prefill. | Every answer must name its sources. |
| Shape versus truth | A reply can be valid JSON and still cite a clause that was never given. | The one verifier is reused: structured citations are converted to bracket labels and checked against the sources given, the approved status and the clause registry. | A made-up citation must be rejected. |
| Test passing for the wrong reason | A hyphenated id (`POL-99`) was rejected as "no citation" because the pattern matches word characters only. | Test rewritten with real-format ids (`tos_v9 7.7`) and a positive case. An id the pattern cannot parse is rejected, which fails safe. | Not applicable. |
| Failed check | v0.4 returned the answer with the problems listed. | Up to 2 retries, feeding back the rejected reply and the verifier's reasons. After the last retry, a refusal with `verification_failed`. An unverified answer is never returned. | Superseded and draft clauses must never be citable. |
| Invalid JSON | A reply that does not parse is a failed attempt. | Counted as an attempt and retried. Tested with a stub model (cases A to D in `test_retry.py`). | Not applicable. |
| Scorer interface | The harness reads `NOT_FOUND` and bracketed citations. | A refusal is returned as `NOT_FOUND` and citations are re-appended as brackets, so the baseline stays comparable. | Not applicable. |
| API outage | 10 rows errored with DNS and "Network is unreachable", including in `plain`, which ruled out the new code (Q23, Q31, Q32, Q33). | Re-ran those four questions, merged by id, refuse to report while error rows remain. 0 remain. | Not a system failure. |

Results (passes out of 76 runs, merged): plain 22, rag_off 72, rag_on 76. Wrong answers: plain 7, rag_off 3, rag_on 0. Abstained: plain 49, rag_off 8, rag_on 8. The prompt, the schema and the retry shipped together, so the rag_off gain from 38 to 72 is not split between them. The retry may be doing the status filter's job in rag_off, so a green rag_off score does not show healthy retrieval. The verifier and forbidden-citation columns are zero by design and no longer measure anything. Attempts were not recorded in this run.

Decisions: schema-constrained output (ADR-024); one verifier, citations converted to it (ADR-025); retry at most twice with feedback (ADR-026); fail closed (ADR-027); keep the scorer interface stable (ADR-028).

Done check met: the verifier rejects an answer with a made-up citation (`test_structured.py`).

## 17 Nov: retrieval failures planted, diagnosed and fixed

Three failure families were diagnosed with `probe.py` and `recall.py`, fixed at their cause, and pinned with tests that need no model calls. Every entry is in `docs/failure-log.md`. Findings:

| Area | Finding | How we handle it | Golden-set trap |
| --- | --- | --- | --- |
| Stale version (FL-001, Q28) | Three versions of clause 2.2 scored within 0.007. With the filter off the superseded v2 clause (14 days) outranked the approved v3 clause (7 days). | Status filter inside the SQL before ranking (ADR-019). Authority rank only breaks ties. Test: filter on puts `tos_v3 2.2` first; filter off reproduces the failure. | T02: the refund window is 7 days, not 14. |
| Rule split across clauses (FL-002, Q07, Q38) | The formula clause 3.5 is dissimilar to the question; clause 3.6 names it. | Pointer expansion: add the clauses a retrieved clause names ("Section X.Y"), same document, one level, status filter kept (ADR-029). 0.1 extra chunks per question, against 4 for k=12 and 6 for neighbouring clauses. | T14: the answer needs the formula clause as well as the clause that points to it. |
| Law versus policy (FL-003, Q29) | No statute in the corpus, and similarity ranks the policy first. | A fictional Digital Goods Consumer Rights Act as source type `statute`, approved, authority rank 0 (migration 003, ADR-030). Ranking stays neutral. Test: policy and statute are both in the top 8; policy outranks statute by similarity. | T03: the law outranks the policy. The escalation half is Phase 3 work. |
| Collateral: number collision | Statute clause 3.3 said "14 days", the T02 number. It surfaced at Q28 rank 3 and the answers explained it. | Changed to 21 days after confirming no other document uses 21. An authored-data fix, not a retrieval fix. | T02 stays a clean trap. |
| Refusal versus denial | Q37 abstained on 2 of 8 rag_on runs. The scorer's `NOT_FOUND` boundary hid the reason. | The scorer now records `refused`, `refusal_reason` and `attempts`. The prompt defines `refused` strictly: only when the sources lack the information (ADR-031). | T13: Q37 expects an answer from tos_v3 2.2. |
| Verifier gap | One earlier Q31 answer carried an uncited statute sentence and passed. | Recorded as a known limit. The verifier checks that citations present are legitimate, not that every claim has one. | Not applicable. |
| Chunk size | Not tested. T14 was handled as a dependency problem, not a size problem. | Fixed-size chunking experiments were not run. Hybrid search and reranking were compared and not adopted. | Not applicable. |

Results: full run after all changes, 38 questions, 2 runs, 0 error rows. plain 18/76, rag_off 73/76, rag_on 76/76 with 0 wrong answers, 0 forbidden citations and 0 verifier problems. rag_on refused on 8 runs, all on Q27, Q35, Q39 and Q40, the questions expected to refuse. Q37 rag_on went from 5/6 to 6/6 after the prompt change. Q27, Q35, Q39 and Q40 are 12/12 on every mode over 3 runs. Plain mode moves between runs and is not affected by these changes.

Decisions: pointer expansion (ADR-029); a statute tier at rank 0 with ranking left neutral (ADR-030); a strict `refused` definition and recorded refusal reasons (ADR-031).

Done check met: each failure has a cause, a fix and a test (FL-001 to FL-003). Open: the law-over-policy decision and human hand-off are agent work, so Q29 stays out of the scorer. Carry-over: golden set v1.1 (Q24 reference omits clause 4.4; Q28 `must_not_cite_files` omits the meeting note; Q29 authoritative source still reads "regulation text (to be read)").

## 18 Nov: shared tables, auth, row-level security and G1

Not started. Plan row: shared customer tables, Supabase Auth and row-level security, the `search_policy()` function, freeze clause IDs and the answer schema. Gate G1 is met when that row is done. This section is written when the work is done.
