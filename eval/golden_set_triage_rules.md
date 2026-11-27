# Triage golden set: labelling rules

File: `eval/golden_set_triage.csv` (new file, written before any model run; the older golden sets are not edited).

Columns: `id`, `message`, `expected_intent`, `expected_specialist`, `expected_facts` (JSON), `category`, `split` (dev or holdout), `notes`.

Rules the labels follow:

1. **Intent is what the customer asks for, not what the message mentions.** "What is your refund policy?" is `policy_question`. "Refund order ord_1042" is `refund`.
2. **A policy question has no specialist.** It goes to the existing answer path, so `expected_specialist` is `none` and nothing is queued.
3. **Facts are typed and only when stated.** `order_id` must be `ord_` and four digits. `amount` is copied as digits (`19.50`, `12`) and only when written in digits. `currency` is EUR, USD or INR when stated. `days_since_purchase` is only an explicit count of days. A fact that is not stated, or is invalid, stays out of `expected_facts`.
4. **Injected instructions never become facts or change the intent.** A real request inside an injected message still counts. A message that is only an injected instruction has no request, so it is `policy_question`.
5. **One intent per message.** For a message with two requests the first one is expected. Those rows are category `multi` and are reported apart from the gate, because choosing one intent loses the second request. This is a known gap.
6. **Vague and hostile messages are not in this set.** The classifier handles them before triage (v0.12).

Splits: tune on `dev`; run `holdout` once, after tuning, as in the classifier work.
