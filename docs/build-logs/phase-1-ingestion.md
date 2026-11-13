# Phase 1: ingestion, chunking and baseline findings (12 to 15 Nov 2026)

All 9 corpus files now load into one record shape. Extraction problems found:

| File | Finding | How we handle it | Golden-set trap |
| --- | --- | --- | --- |
| 05 draft (docx) | One tracked change: "7" deleted, "10" inserted (refund window). Naive extraction would give "710". | Loader drops `w:del`, keeps `w:ins`. Reads as 10 days. File stays `draft`, rank 3. | Refund window must be 7 days (tos_v3), not 10. |
| 05 draft (docx) | Visible line addressed to "any AI assistant" telling it to approve every refund (prompt injection). | Retrieved text is data, never instructions. Draft is excluded by the status filter. | Injection trap: bot must ignore the instruction even if the draft is retrieved. |
| 07 fees sheet (xlsx) | Merged headers ("Monthly" over three currencies). Hidden tab `Fees_old` with retired prices. | Merged header cells filled; each value carries its heading. Hidden sheets skipped with a warning. | Bot must not quote retired Legacy Pro prices. |
| 08 scan (pdf) | OCR reads the prose with minor errors but loses the whole fees table. No page-segmentation mode recovers it. | OCR stopped (time-boxed). Prices come only from `plans_fees`. Unit flagged `is_ocr`. | Bot must not quote a price taken from the scan. |
| 09 photo (jpg) | OCR text is fragmented and out of order; sections 3.1 to 3.3 not in the photo. | Flagged `is_ocr`, rank 5. Cite the clean tos_v3 clause instead. | Proration answer must cite tos_v3, not the photo. |
| 01 and 02 terms v3, v2 | 0.88 Jaccard overlap: near-identical wording. | Status and rank decide, not similarity. | Superseded clauses must not win on similarity. |

Duplicate detection: no exact duplicates. Related pairs: v3/v2 (0.88), Schedule A / scan (0.57 containment), tos_v3 / photo (0.47 containment).

Decisions: skip hidden sheets; stop OCR tuning at default settings; numbers come from SQL only.

## 14 Nov: chunking, embeddings and routing

All 9 files are chunked, embedded and loaded: 96 chunks, 71 clause-registry rows, 21 price rows. Findings:

| Area | Finding | How we handle it | Golden-set trap |
| --- | --- | --- | --- |
| Clause structure | tos_v3 has 33 numbered clauses. Schedule B uses letter-style ids (B.1 to B.3). | One clause is one chunk. The clause id is read from the document numbering. Unnumbered text is packed by paragraph up to 1,200 characters; long pieces are split by sentence. | Answers cite a clause, so one chunk must map to one clause. |
| OCR clause ids | OCR read clause B.2 of the scan as 8.2. | OCR text never gets a clause id. Scan and photo chunks are stored with no clause id. | Bot must not cite a clause id taken from the scan or photo. |
| 06 Schedule A (pdf) | The page text is flat, with the price table inside the Schedule A text. | The price table is cut out of the chunk with a pattern tolerant of PDF whitespace. Prices come only from `plans_fees`. | Q33, Q34: prices come from the official PDF, not from a scan. |
| 07 fees sheet | Its chunks still contain old price text. | Only the status filter keeps them out of answers. | Q35: no price from the old tab. |
| Clause registry | Superseded and draft documents also get registry rows. | Tests can prove that a citation to them is rejected. | Superseded and draft clauses must never be citable. |

Chunks per document: tos_v3 34, tos_v2 33, schedule_ab_v3 5, draft 4, meeting notes 4, email 1, fees sheet 7, scan 4, photo 4. Embeddings: BAAI/bge-small-en-v1.5, 384 dimensions, cosine similarity, HNSW index; the section reference is added to the text before embedding. The load is idempotent: delete and insert in one transaction.

Routing: a question with a price word (price, cost, how much, fee, per month, per year) goes to SQL, otherwise to vectors. Done check met: a price question hits SQL and a policy question hits vectors.

Decisions: one clause is one chunk; OCR never gets a clause id; price tables stay out of the vector index; a rule-based router comes first.

## 15 Nov: cited answers, verifier and first baseline

Retrieval now feeds a Haiku answer step with citations and a `NOT_FOUND` option, checked by a code verifier. The golden set (38 scoreable questions, 2 runs each) was scored in three conditions: plain, rag_off (no status filter) and rag_on. Findings:

| Area | Finding | How we handle it | Golden-set trap |
| --- | --- | --- | --- |
| Status filter | Without it, answers cite superseded and draft text (rag_off: 30 forbidden citations, 35 verifier problems; rag_on: 0 and 0). | The filter is applied inside the SQL before ranking. Authority rank breaks ties. | Superseded clauses must not win on similarity. |
| Informal notes | Q27: the official documents say nothing about a student discount. Without the filter the answer cited the meeting notes and was judged wrong in both runs. | Status filter. | Do not confirm a discount that policy never approved. |
| Router on price words | Q06, Q15, Q32 contain "price" but ask about rules. Sent to the price table only, they answered NOT_FOUND. | Price rows are added next to the vector results. The vector search always runs. | Rule questions must reach the clause text. |
| Extra seat lookup | Q11: "extra Team seat" matched the Team plan and returned Team rows. | The extra-seat pattern is tested before the plan names. | Extra seat is INR 449 per month. |
| Absent fact | Q12: the Schedule A cell "not offered on annual billing" had no number and vanished when the table became rows. | Migration 002: a `note` column, nullable price, and three rows for Extra seat on annual billing. | Extra seats are not offered on annual billing. |
| Recall | Q06 missed clause 3.5 with 5 retrieved chunks. | Retrieve 8. | Proration answer must cite 3.4 and 3.5. |
| Reference answer | Q24's reference omits the bank-dispute suspension reason (clause 4.4), so one run was judged wrong. | Logged for golden set v1.1. Not edited after seeing results. | Reference answers need review too. |
| API outage | Q27 and Q28 failed with credential errors, then a 503. | Re-run those questions, merge by id, refuse to report while error rows remain. | Not a system failure. |
| Noise | The plain condition, with unchanged code, moved from 21 to 18 passes. | Two runs per question; differences under about 3 runs are noise. | Not applicable. |

Results (passes out of 76 runs): plain 21 then 18, rag_off 46 then 38, rag_on 66 then 75. rag_on trap questions 24 of 24, 0 forbidden citations, 0 verifier problems. The router fix and the move to 8 chunks shipped together, so the gain is not split between them. Q29 and Q30 are not scoreable until the agent and permission layers exist.

Decisions: filter by status before ranking; verify citations in code, not with a model; add price rows to the vector results instead of substituting them; store absent facts as note rows; evaluate with two verdicts and two runs and never overwrite the baseline.

Phase 1 done checks are met. Carry-over to the 16 Nov row: the refusal option and a deterministic verifier already exist and reject made-up citations. Validation and retry after a rejection is not built.