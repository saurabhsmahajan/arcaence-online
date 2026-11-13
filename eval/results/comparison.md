# Baseline vs after router fix

Error rows remaining in either run: 0. Q27 and Q28 rows in the 'after' set come from re-runs after an API outage.

| Mode | Baseline | After | After: normal | After: trap | Wrong | Forbidden cited | Verifier problems |
|---|---|---|---|---|---|---|---|
| plain | 21/76 | 18/76 | 8/52 | 10/24 | 7 | 0 | 0 |
| rag_off | 46/76 | 38/76 | 31/52 | 7/24 | 5 | 30 | 35 |
| rag_on | 66/76 | 75/76 | 51/52 | 24/24 | 1 | 0 | 0 |

Failing rag_on rows after the fix:

- Q24 run2: wrong
