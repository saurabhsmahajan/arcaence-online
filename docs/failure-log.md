# Retrieval failure log

One entry per failure. Each entry has a cause, a fix and a test; an entry without all three is not done. Probe any question with `uv run python probe.py <id>` from `rag/`. Retrieval tests run without model calls.

| ID | Family | Trap | Question | Cause | Fix | Test | State |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FL-001 | Stale version | T02 | Q28 | Near-identical versions of one clause | Status filter before ranking (ADR-019) | `rag/test_retrieval_failures.py` | Fixed |

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
- Only one question is probed. T06 (Q31, a superseded rule repeated in an email) is not probed yet.
- The meeting note `notes_policy_review` appeared at rank 4 with the filter off, but it is not in Q28's `must_not_cite_files` (which lists 02 and 05). The verifier still blocks it because its status is `informal`. The field is incomplete; correct it in golden set v1.1, not now.