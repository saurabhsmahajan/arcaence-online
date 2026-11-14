# Baseline vs after router fix vs structured answers (v1)

Error rows in any run: 0. Structured run = structured_v1 with Q23, Q31, Q32, Q33 re-run after a local network outage and merged by id.

| Mode | Baseline | After router fix | Structured | Structured: normal | Structured: trap | Wrong | Abstained | Forbidden cited | Verifier problems |
|---|---|---|---|---|---|---|---|---|---|
| plain | 21/76 | 18/76 | 22/76 | 11/52 | 11/24 | 7 | 49 | 0 | 0 |
| rag_off | 46/76 | 38/76 | 72/76 | 48/52 | 24/24 | 3 | 8 | 0 | 0 |
| rag_on | 66/76 | 75/76 | 76/76 | 52/52 | 24/24 | 0 | 8 | 0 | 0 |

Failing rag_on rows (structured):

