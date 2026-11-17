# Retrieval failure log

One entry per failure. Each entry has a cause, a fix and a test; an entry without all three is not done. Probe any question with `uv run python probe.py <id>` from `rag/`. Retrieval tests run without model calls.

| ID | Family | Trap | Question | Cause | Fix | Test | State |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FL-001 | Stale version | T02 | Q28 | Near-identical versions of one clause | Status filter before ranking (ADR-019) | `rag/test_retrieval_failures.py` | Fixed |
| FL-002 | Rule split across clauses | T14 | Q07, Q38 | Formula clause 3.5 is dissimilar to the question; 3.6 points to it | Pull in clauses a retrieved clause names (ADR-029) | `rag/test_retrieval_failures.py` | Fixed |

## FL-001: stale version outranks the current one

**Symptom.** With the status filter off, Q28 ("I read that I have 14 days to get a refund...") returns the superseded v2 clause 2.2 (14 days) as the top result, ahead of the approved v3 clause 2.2 (7 days).

**Probe.** `uv run python probe.py Q28` shows both lists side by side.

| Rank | Filter off | Status | Score | Filter on | Score |
| --- | --- | --- | --- | --- | --- |
| 1 | tos_v2 2.2 | superseded | 0.840 | tos_v3 2.2 | 0.836 |
| 2 | tos_v3 2.2 | approved | 0.836 | tos_v3 2.1 | 0.756 |
| 3 | draft_v3_5 2.2 | draft | 0.833 | tos_v3 2.3 | 0.712 |

**Cause.** The three versions of clause 2.2 differ by one number (14, 7 and 10 days), so the embeddings are almost identical: the score spread across them is 0.007. Similarity cannot tell an approved clause from a superseded one. The question also contains "14 days", which echoes the stale text and tips the order. The authority rank is only a tiebreaker, and the scores are never exactly equal, so it does not help. A second cost: with the filter off, only 3 of the 8 slots hold approved text, so stale and informal text crowds out useful clauses.

**Fix.** Filter by status inside the SQL query, before ranking, so non-approved text never reaches the model (ADR-019, refining ADR-004). The verifier is the second line: it rejects a citation to a non-approved document even if retrieval lets one through.

**Test.** `rag/test_retrieval_failures.py`, case FL-001, no model calls. It asserts that with the filter on every result is approved and `tos_v3 2.2` is first. It also asserts that with the filter off the stale result is still returned and v2 still outranks v3, so the planted failure stays reproducible and a change in the data is noticed.

**What this test does not cover.**

- The filter trusts the `status` column. If a new version were loaded and the old one not marked superseded, the filter would let both through. There is no test for that yet.
- Only one question is probed. T05 (Q31, a meeting note contradicting the policy) and T06 (Q32, a superseded rule repeated in an email) are not probed yet.
- The meeting note `notes_policy_review` appeared at rank 4 with the filter off, but it is not in Q28's `must_not_cite_files` (which lists 02 and 05). The verifier still blocks it because its status is `informal`. The field is incomplete; correct it in golden set v1.1, not now.

## FL-002: the formula clause is not retrieved

**Symptom.** Q07 needs clauses 3.5 and 3.6. With the status filter on and k=8, the top 8 holds only 3.6; clause 3.5 ranks 9th and never reaches the model. Clause 3.5 is the weak spot across the whole family: it ranks 6th for Q06, 9th for Q07, 5th for Q38 and 2nd for Q32.

**Probe.** `uv run python recall.py` lists, for every golden-set question, the rank of each required clause with the filter on and off (required clauses are read from `authoritative_source`). With the filter on, 27 of 28 questions have every required clause in the top 8; at k=5 it is 25 and at k=3 it is 23. With the filter off it is 23 of 28 at k=8.

**Cause.** The upgrade price is one rule spread over three clauses (3.4, 3.5, 3.6), and the clause with the formula, 3.5, shares few words with how customers ask ("20 hours into my cycle" matches 3.6's "first 24 hours" and 3.4's "upgrades take effect immediately"). Clause 3.6 says "Section 3.5 does not apply if...", a pointer to the missing clause, but similarity search cannot follow pointers. This is a dependency problem more than a chunk-size problem: each clause is a sound chunk.

**Options compared** (`uv run python recall_expand.py`, 28 questions, 36 approved clause chunks):

| Strategy | Questions fully covered | Avg chunks per question | Max chunks |
| --- | --- | --- | --- |
| k=8 (before) | 27/28 | 8.0 | 8 |
| k=12 | 28/28 | 12.0 | 12 |
| k=8 + cross-reference | 28/28 | 8.1 | 9 |
| k=8 + neighbours | 28/28 | 14.1 | 19 |
| k=8 + both | 28/28 | 14.1 | 19 |

All four fix the same single miss (Q07). They differ only in cost.

**Fix.** `expand_references()` in `rag/retrieval.py`, called in `answer_question` after the vector search. For each retrieved clause it finds `Section X.Y` in the text and fetches that clause from the same document. The status filter still applies, so expansion cannot add non-approved text. One level only (ADR-029). Added rows carry `score = None`.

**Test.** `rag/test_retrieval_failures.py`, case FL-002, no model calls. For Q07 and Q38 every required clause must be present after expansion, expansion may add at most 2 chunks, and no non-approved row may appear. It also asserts that Q07 still lacks 3.5 without the expansion, so the planted failure stays reproducible. Result: Q07 top 8 had only 3.6 and expansion added 1 chunk; Q38 already had all three and expansion added 0.

**Regression check.** Scorer run `after_xref` on Q06, Q07, Q32 and Q38: zero error rows; `rag_on` 2/2 on each question, same as before; `rag_off` Q06 went from 0/2 to 2/2.

**What this does not show.**

- No scored gain in `rag_on`. Q07 passed before the fix because the model answered correctly without 3.5, so the fix removes a fragility and does not move a score. The `rag_off` Q06 change is consistent with the fix but is one question and two runs.
- Only one question separates the strategies, and the corpus is small (36 approved clause chunks). Cross-reference is chosen on cost and reasoning, not proven the best.
- It only helps where a pointer exists, and only for the exact phrase "Section X.Y". Q06 (3.5 at rank 6) and Q40 (5.3 at rank 6) are still fragile and have no pointer to follow.
- Hybrid search and reranking were considered and not adopted: no miss remains at k=8 to justify the extra moving parts. Revisit when a miss appears that has no pointer, or the golden set grows.