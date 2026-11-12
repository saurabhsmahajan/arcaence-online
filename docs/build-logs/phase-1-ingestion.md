# Phase 1: ingestion findings (12 Nov 2026)

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