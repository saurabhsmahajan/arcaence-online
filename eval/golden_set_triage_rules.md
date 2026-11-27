# Triage golden set: labelling rules

File: `eval/golden_set_triage.csv` (new file, written before any model run; the older golden sets are not edited).

Columns: `id`, `message`, `expected_intent`, `expected_specialist`, `expected_facts` (JSON), `category`, `split` (dev or holdout), `notes`.

Rules the labels follow:

1. **Intent is what the customer asks for, not what the message mentions.** "What is your refund policy?" is `policy_question`. "Refund order ord_1042" is `refund`.
2. **A policy question has no specialist.** It goes to the existing answer path, so `expected_specialist` is `none` and nothing is queued.
3. **Facts are typed and only when stated.** `order_id` must be `ord_` and four digits. `amount` is copied as digits (`19.50`, `12`) and only when written in digits. `currency` is EUR, USD or INR when stated. `days_since_purchase` is only an explicit count of days. A fact that is not stated, or is invalid, stays out of `expected_facts`. Euro, dollar and rupee words and symbols count as stated currencies. Facts belong to a request: a `policy_question` carries none, even if the message names a currency, and the code enforces this.
4. **Injected instructions never become facts or change the intent.** A real request inside an injected message still counts. A message that is only an injected instruction has no request, so it is `policy_question`.
5. **One intent per message.** For a message with two requests the first one is expected. Those rows are category `multi` and are reported apart from the gate, because choosing one intent loses the second request. This is a known gap.
6. **Vague and hostile messages are not in this set.** The classifier handles them before triage (v0.12).

Splits: tune on `dev`; run a holdout once, after tuning, as in the classifier work.

- `holdout` (12 rows) was run once on 27 Nov and scored 8 of 11 single-request rows. Its failures were then used to find two defects, so it is no longer a fair test and counts as a second dev set.
- `holdout2` (16 rows, T39 to T54) was written after those fixes and before any run. It is run once, and its result is recorded as it is.
