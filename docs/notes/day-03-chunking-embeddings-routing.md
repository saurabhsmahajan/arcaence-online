# 14 Nov study notes: chunking, embeddings and routing

Nov 13, 2026 · @saurabh

## What 14 Nov covered

The 14 Nov row is complete: the corpus is now cut into citable chunks, embedded locally, stored in Postgres with a vector index, and a rule-based router sends price questions to SQL and policy questions to vectors.

| Step | What we built | Where | Result |
| --- | --- | --- | --- |
| 1 | Chunker: one clause becomes one chunk | `ingest/chunk.py` | 96 chunks across 9 documents |
| 2 | Stable clause IDs and the registry | `chunk.py`, `load_chunks.py` | 71 registry rows |
| 3 | Local embeddings (bge-small-en-v1.5) | `ingest/embed.py` | 384 dimensions per chunk |
| 4 | Repeatable load plus HNSW index | `ingest/load_chunks.py`, migration 001 | 96 chunks stored with vectors |
| 5 | Plans and fees table | migration 001 | 21 rows, already seeded |
| 6 | Router: price to SQL, policy to vectors | `retrieval.py` | done check passes |

The done check on the plan reads: a price question hits SQL, a policy question hits vectors. It passes. "How much does the Pro plan cost per month in euros?" returns Pro, monthly, EUR, 19 from `plans_fees`. "How long do I have to ask for a refund?" runs a vector search.

Each concept below has the same four parts: what it means in plain words with an example, why we need it, and how it is built in this project. The architecture and the architect's view follow the concepts.

## Concepts 1 to 4: preparing the knowledge

These four concepts turn documents into something a search can use. They run once, at load time.

### 1. Chunking

**In plain words.** Chunking means cutting a document into small pieces, so a search can return the one piece that answers the question and not the whole document. **Example:** the terms of service are cut into one piece per clause, such as *2.2 You may request a refund of a one-off purchase within 7 days.* If the pieces are too big, a refund question also drags in cancellation and data deletion, and the answer is lost in noise. If they are too small, "within 7 days" loses the sentence that says what it applies to.

**Why we need it.** The chunk is the unit of everything that follows: it is what gets embedded, what gets retrieved, and what gets cited. A bad cut cannot be repaired later.

**How it is built here.** We cut on the document's own structure, not on a fixed character count. One numbered clause is one chunk. The section title is kept as `section_ref`, so a clause knows where it sits. Text without numbered clauses (emails, meeting notes) is packed paragraph by paragraph up to 1,200 characters, and a longer piece is split at sentence ends. Every chunk keeps its provenance: `doc_id`, `section_ref`, `page` and the `is_ocr` flag. The chunker had to handle three hazards we found by looking at the output:

- Section headings became chunks of their own (7 in `tos_v3`). They were dropped, because the heading is already stored in `section_ref`.
- The approved fees and disputes PDF arrives as one flat line, with clauses `B.1` to `B.3` inline. A pattern for letter-style IDs splits them.
- The price table inside that PDF was cut out before chunking (concept 8 explains why).

*Diagram: one clause becomes one chunk with its provenance*

The highlighted clause becomes one row in the `chunks` table. The row keeps the clause number, the document, the section and the OCR flag next to the text and its vector.

### 2. Stable clause IDs and the registry

**In plain words.** Every clause gets a name taken from the document's own numbering, such as `2.2` or `B.2`. A registry lists every name that really exists. **Example:** if the assistant answers "see clause 2.2", a verifier looks up `2.2` for that document in the registry. If the row is missing, the model invented the citation and the answer is rejected.

**Why we need it.** A citation is only worth something if a machine can check it. The ID must also be stable. An ID built from chunk position would renumber everything after one edit and break every old citation.

**How it is built here.** The ID is read from the numbering in the text, either digits (`2.2`) or a letter and a digit (`B.1`). The registry key is `(clause_id, doc_id)`, so clause `2.2` of v2 and `2.2` of v3 are different rows. The load wrote 71 registry rows. Superseded and draft documents get rows too, so a later test can prove that a citation to an old clause is rejected. One rule protects the registry: **OCR text never gets a clause ID.** The OCR read `B.2` as `8.2`, which exists in no document. The chunk is still stored, flagged `is_ocr`, but it can never be cited by number.

### 3. Embeddings and cosine similarity

**In plain words.** An embedding model turns a piece of text into a list of numbers, 384 of them here. Think of it as a point in a 384-dimensional space. Texts with similar meaning land near each other, and "near" is measured by the angle between the two arrows (cosine similarity). **Example:** "How long do I have to ask for a refund?" lands close to the clause about requesting a refund within 7 days, although they share few words. A keyword search would miss that.

**Why we need it.** People paraphrase. Matching on meaning is what lets one question find the right clause however it is worded.

**How it is built here.** `fastembed` runs `BAAI/bge-small-en-v1.5` locally, so there is no API key and no cost. The first run downloads about 67 MB. We embed each chunk together with its section ("Schedule B. B.2 While a dispute..."), while the stored `content` stays clean. Questions go through `query_embed`, because this model expects a short instruction in front of a question. A first check on `tos_v3` gave 384 dimensions and sensible neighbours: the refund question scored 0.845 against `2.3`, 0.826 against `2.2` and 0.805 against `3.3`.

### 4. The vector index (HNSW)

**In plain words.** Comparing a question with every chunk is fine for 96 chunks and too slow for millions. HNSW builds a layered map of near neighbours, like highways on top and local streets below, so a search jumps close to the answer quickly. It is approximate: it can miss a true neighbour in return for speed.

**Why we need it.** It keeps search fast as the corpus grows. We set it up now so the design does not change later.

**How it is built here.** The schema has `create index chunks_embedding_idx on chunks using hnsw (embedding vector_cosine_ops)`. The operator class matches the `<=>` cosine distance used in the query, and the score we print is `1 - distance`. At 96 rows Postgres will probably scan the table directly. The index earns its place later.

## Concepts 5 to 8: loading, routing and what the baseline showed

These concepts cover how the prepared knowledge is stored, how a question picks its path, and what the first unfiltered search taught us.

### 5. Repeatable (idempotent) loading

**In plain words.** A loader is idempotent when running it twice leaves the same database as running it once. **Example:** after fixing the chunker we reload. The loader deletes the old chunks and registry rows for these documents, inserts the new ones, and commits only if every step worked. If something fails halfway, the transaction rolls back and the previous data is still there.

**Why we need it.** We will change the chunking rules and re-embed many times. Without this, every run would add duplicates, or leave a half-loaded corpus behind.

**How it is built here.** `ingest/load_chunks.py` reads the records, chunks them, embeds all chunks, then does the delete and the inserts inside one transaction. The vector is sent as text and cast with `::vector`. The connection string comes from `.env`, so no secret is in the code. Result: 96 chunks and 71 registry rows for 9 documents, and the `documents` table already held its 9 rows from Day 1.

### 6. Routing by data type

**In plain words.** The router picks the tool before any search happens. A question that needs one exact number goes to SQL. A question about policy wording goes to vector search. **Example:** "How much does the Pro plan cost per month in euros?" goes to `plans_fees` and returns 19. "How long do I have to ask for a refund?" goes to the vectors.

**Why we need it.** Vector search returns text that is similar to the question, and similar text can be the wrong version or a garbled scan. A price must be exactly one value, so it comes from a table, never from a search.

**How it is built here.** `retrieval.py` holds a plain rule: a question with a price word (price, cost, how much, fee, per month, per year) takes the SQL path. The SQL path reads the plan, currency and billing period out of the question and filters `plans_fees` to match. The word "annual" alone does not trigger it, so "Can I cancel my annual plan?" correctly goes to the vectors. A rule is free, instant and easy to test, and it has a known weakness: "What do I pay for Pro?" contains no price word and would go to the vectors. That sentence belongs in the golden set. A model-based router can replace the rule later, and the same tests will say whether it is better.

### 7. Similarity cannot tell authority

**In plain words.** Vector search ranks by meaning, not by trustworthiness. A superseded clause and the current one say nearly the same thing, so they score nearly the same. **Example, from today's run:** for "How long do I have to ask for a refund?" the top four results were v2 `2.3`, v3 `2.3`, v2 `2.2` (**14 days**, superseded) and the draft `2.2` (**10 days**). The approved v3 `2.2`, which says **7 days**, was not in the top four. v2 `2.3` and v3 `2.3` are the same text and tied at 0.845.

*Diagram: unfiltered refund search, top results*

The dashed row is the right answer. It scored 0.826, the same as the draft in fourth place, and fell outside the four results returned. Rows with a coloured border are coloured by status: green approved, amber superseded, red draft.

**Why we need it.** This is the central failure of RAG on customer documents that contradict each other. A system that answers from the top result would say 14 days, confidently. We ran the search without any filter on purpose, to record this as the baseline.

**How it is built here.** Nothing yet: that is the point. Tomorrow's work adds the status filter before similarity, with authority rank to break ties, and the golden set measures the improvement against today's baseline. Two other readings of the same run matter. First, we retrieve several chunks and not one, and the scorer must check that the right clause is among the top few, not only first. Second, the cancellation question scored only about 0.65 and surfaced no cancellation clause. A low best score is a signal, and a minimum-score threshold is how the assistant will learn to say "I could not find this".

### 8. Keeping prices out of the vector store

**In plain words.** Prices live in one exact table. Text that merely contains prices is kept out of the vector index. **Example:** the Schedule A page has a price table followed by three sentences (prices exclude tax, annual is ten times monthly, the checkout price is what you pay). We cut the table out and kept the sentences.

**Why we need it.** A second copy of the prices is a second source of truth. A copy that went through PDF extraction or OCR can have a changed digit and nothing would flag it. The one source for prices is `plans_fees`.

**How it is built here.** `plans_fees` has 21 rows: 12 monthly prices, plus 9 annual prices that are the monthly price times ten for Starter, Pro and Team (an extra seat is not offered annually). The chunker removes the price table from the Schedule A chunk with a pattern that tolerates PDF whitespace. One gap remains: the informal spreadsheet's chunks still contain price text, including an "Old price list" line, and appeared in a search result. The status filter must keep informal documents out, and that is tomorrow's test.

## Architecture after 14 Nov

The system now has two paths. A load path runs once and fills the database. A question path picks SQL or vectors before it searches.

*Diagram: architecture after 14 Nov: load path and question path*

**How to read it.** The bottom row is load time, left to right: the corpus goes through the loaders into Records, the chunker cuts them into 96 chunks, and the embedder adds a 384-number vector to each. The result lands in Postgres. The top row is question time. The router looks for price words. A price question goes along the top arrow to a SQL lookup on `plans_fees` and gets exact rows. Any other question goes to the vector search over `chunks`. Dashed boxes are planned for 15 Nov, so today there is no status filter between the search and the table.

**What changed since v0.2**

- The chunker, the embedder, the `chunks` and `clause_registry` tables and the router were planned in v0.2 and now exist.
- The Schedule A price table is cut out before chunking, so prices live only in `plans_fees`.
- OCR text is stored and flagged, but never receives a clause ID.
- The vector search is unfiltered, which is the baseline we measure the status filter against.

## The architect's view

Every decision today puts a check in a place where it can be tested, and each one has a cost we accept knowingly.

| Decision | Why | What it costs |
| --- | --- | --- |
| Chunk by clause structure, not by fixed size | Sharp matches, and each chunk is a citable unit | Depends on documents being numbered; unnumbered ones fall back to paragraphs |
| Clause ID read from the document's numbering | Stable across edits, checkable by a verifier | OCR text can never be cited by number |
| Local embedding model | No cost, no data leaves the machine, reproducible | A small model; hosted models may rank better |
| Route before search, with plain rules | Deterministic and easy to test | Brittle on unusual phrasing |
| Prices only from the SQL table | One source of truth for every number | Price text in documents must be cut out of the vectors |
| Index every document, filter at query time | Superseded and draft clauses exist, so tests can prove they are excluded | If the filter fails, wrong versions are retrievable |
| One-transaction repeatable load | Safe to rerun after any change | Re-embeds everything each run, fine at this size |

**Defence in depth, not one control.** The wrong-version problem is blocked at several layers: the status filter keeps old versions out of the results, authority rank breaks ties, and the registry check rejects a citation to a clause that is not approved. Any one layer can fail without the customer seeing a wrong answer, and the golden set tests each layer on its own.

**What could go wrong**

- The status filter is not built yet. Until tomorrow, retrieval returns superseded and draft clauses, as today's baseline shows.
- The router is a rule. A price question without a price word goes to the vectors and could return text that looks like an answer.
- The model name is not stored with the vectors. If we change the model, every chunk must be re-embedded, and mixing two models in one index gives meaningless scores. Recording the model name beside the vectors is a cheap safeguard to add.
- Clause IDs are scoped to a document version. A new version gets its own registry rows, so old citations keep pointing at the version they were made against.

**The governance angle.** The registry, the provenance fields (`doc_id`, `section_ref`, `page`, `is_ocr`) and the load transaction are audit evidence. For any answer we can later show which chunk of which version supported it, and whether that text came from OCR. That is what a reviewer of an AI system asks for, and it is built into the data model from the start.

## Findings, self-test and what comes next

Today's work produced nine findings. Each one is handled now or becomes a test for 15 Nov.

| # | Finding | What we did | Test it feeds |
| --- | --- | --- | --- |
| 1 | Section headings became chunks of their own | Dropped; the heading stays in `section_ref` | Chunker check: no heading-only chunks |
| 2 | The approved PDF is one flat line with clauses `B.1` to `B.3` inline | Letter-style IDs split inline | A dispute question must cite `B.2` |
| 3 | The Schedule A price table sat inside a chunk | Cut before chunking | A price answer comes from `plans_fees` only |
| 4 | OCR read `B.2` as `8.2` | OCR text never gets a clause ID | A citation to `8.2` is rejected |
| 5 | Unfiltered search ranks v2 (14 days) and the draft (10 days) above the approved 7 days | Baseline recorded; status filter next | The refund window must be 7 days |
| 6 | v2 `2.3` and v3 `2.3` are identical and tie | Authority rank breaks ties next | Same refund test |
| 7 | The cancellation question finds no cancellation clause, best score about 0.65 | Noted; score threshold to design | Find v3 `3.2` or say it was not found |
| 8 | The informal spreadsheet, with an old price list, is in the vectors | Status filter next | The old price list never appears |
| 9 | A price question without a price word would skip SQL | Added to the golden set | "What do I pay for Pro?" must give the SQL price |

### Self-test

1. **Why is one clause one chunk, and not a fixed number of characters?** A clause is a complete idea with its own number, so it matches sharply and can be cited. A fixed cut can split a rule from the thing it applies to.
2. **Why does OCR text never get a clause ID?** OCR can misread an ID, such as `B.2` as `8.2`, and an invented ID would look real in the registry. The chunk is kept, flagged `is_ocr`, and cannot be cited by number.
3. **Why embed the section title with the clause?** It gives the vector the context of where the clause sits, while the stored content stays clean.
4. **Why does the load delete and insert inside one transaction?** So a rerun gives the same database, and a failure halfway rolls back instead of leaving a half-loaded corpus.
5. **Why do prices come from SQL and not from search?** A price must be one exact value. Search returns similar text, which may be an old version or a garbled scan.
6. **The refund search put 14 days and 10 days above the approved 7. What does that show?** Similarity measures meaning and not authority. Status and authority rank must be applied outside the similarity score.

### What comes next

The 15 Nov row is the status filter before similarity, the cited answer, the verifier, and the golden-set scorer with a baseline built from the table above. Housekeeping that is still open: ADR-010 to ADR-014 are not yet in `decisions.md`, today's decisions need their own ADRs (clause-level chunking, no clause IDs from OCR, price table kept out of vectors, rule-based router first), and the architecture page needs a v0.3 for today's changes. Blog post 2 is due on 20 Nov.
