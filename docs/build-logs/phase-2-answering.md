# Phase 2: structured answers, failure diagnosis and access (16 to 18 Nov 2026)

Status: complete. The 16, 17 and 18 Nov rows are done and gate G1 was met on 20 Nov 2026.

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

Done check met: each failure has a cause, a fix and a test (FL-001 to FL-003). Open: the law-over-policy decision and human hand-off are agent work, so Q29 stays out of the scorer. Golden set v1.1 was completed on 17 Nov (Q24 reference, Q28 forbidden list, Q29 source); see eval/golden_set_changelog.md.

## 18 Nov: shared tables, auth, row-level security and G1

The database now decides who sees what, the knowledge base sits behind one guarded function, and the two shapes other parts depend on are frozen. Work finished on 20 Nov. Findings:

| Area | Finding | How we handle it | Test |
| --- | --- | --- | --- |
| Shared customer tables | The desk needs customers, orders and invoices. `customer_id` is repeated on each row so one policy can cover every table. | Migration 004: customers (plan, billing, currency, status, `auth_user_id`), orders, invoices. Two synthetic customers: cust_001 (Pro, monthly, EUR) and cust_002 (Team, annual, USD). RLS on, no policies, so nothing is readable until a policy says so. | Row counts after apply. |
| Login linked to a customer | A row-level policy needs to know which customer the logged-in user is. | Two Supabase Auth users linked by email to the two customers (migration 005). `current_customer_id()` is a security-definer helper that reads `customers` by `auth.uid()` (migration 006). | Link check after apply. |
| Row-level security | A customer must see only their own rows. This is the golden set's Q30 case: cust_001 asks about cust_002. | Three select policies, `customer_id = current_customer_id()`, for the `authenticated` role only. Anonymous access revoked. | `test_rls.py`, 10 checks with simulated logins (`set local role` plus `request.jwt.claims`). Q30 is blocked at the database. |
| The guarded door | The knowledge tables had no explicit lockdown. Supabase gave the API roles no default select, but that is a default, not a rule. | `search_policy()` (migration 007): approved clauses only, ordered by distance then authority rank, limit capped at 50, security definer, granted to `authenticated` and `service_role` only. Direct access to documents, chunks, clause_registry and plans_fees revoked. | `test_search_policy.py`: a frozen reference query and the function return identical rows on all 40 golden questions at k=8, plus door checks. |
| Retrieval switched to the door | `vector_search` read the tables directly. A test comparing it with the function would become a comparison with itself. | `vector_search` calls `search_policy()` when `approved_only`. The unfiltered direct query remains for evaluation only. The reference query is frozen inside the test. | Offline tests pass; a scorer subset re-run saved as `after_door_*`. |
| Frozen contracts | Citations, the verifier, the golden set, and later the MCP server and agents depend on clause ids and the answer schema. | `contracts/clause_ids_v1.csv` (80 `(doc_id, clause_id)` pairs) and `contracts/answer_schema_v1.json`. The latest version is the contract. The freeze script refuses to overwrite a version. | `test_contracts.py`: schema equals the frozen file, all 80 ids still present, plus two checks that prove the test can fail. |

Decisions: the guarded database door and the table lockdown (ADR-032); frozen contracts (ADR-033).

Known limits, recorded in ADR-032:
- Python connects as the database owner, which bypasses RLS. The guarantee holds for the API roles, not yet for our own code.
- `expand_references` still reads clauses directly. It needs an equivalent restricted function.
- The verifier checks provenance, not that a clause supports every claim (unchanged).
- The escalation half of FL-003 (law outranks policy, human hand-off) is Phase 3 agent work.

Phase 3 inherits: a restricted database role for agents, a clause-lookup function equivalent to `search_policy()`, and the escalation step.

Commits: 783f766 (004), 54bdac1 (005, 006, `test_rls.py`), 9878e58 (007, `test_search_policy.py`), e44c35a (retrieval switch), 38825de and dc468ac (contracts), d6b51d0 (ADR-032, ADR-033).

Done check met: customer A cannot read customer B's rows (Q30 blocked at the database and tested), retrieval goes through `search_policy()` with unchanged results, and clause ids and the answer schema are frozen with a test that fails on drift. **Gate G1 is met.**
