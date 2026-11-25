# Arcaence Online Project (AOP)

A base project for building agentic AI on a web platform. It starts with a RAG service, an MCP server and a multi-agent support desk for a fictional platform, **Arcaence Online**, and will grow in layers: evals, observability, security, governance and cloud.

> **Everything here is synthetic.** Arcaence Online is fictional. Its terms, fees, emails, notes and customers are invented for testing. They are not real terms of any real company. Results are directional: synthetic data, small test sets, one reviewer.

## The idea

Three layers, one problem:

| Layer | Job | Question it answers |
|---|---|---|
| RAG | Reads approved policy, answers with citations, refuses when the policy is silent | What does the policy say? |
| MCP server | Returns live facts and performs actions inside role limits | What is true for this customer, and what may be done? |
| Multi-agent desk | Routes cases, combines policy and facts, sends risky actions to a human | How is a whole case resolved safely? |

## Status

| Part | Status |
|---|---|
| Phase 0: synthetic corpus, traps list, core golden set | Done |
| RAG (ingestion, grounding, access control, evals, service) | In progress (ingestion, grounding, verified answers and access control done, gate G1 met) |
| MCP server | In progress (read tools, masking, fixed role, write tools, privacy tools, accessibility tool, policy server, resource and prompt, attack harness and Inspector evidence done) |
| Multi-agent desk | Not started |

Target for the first version (AOP v1): 30 November 2026. The plan is gate-based: G1 (RAG foundation), G2 (MCP attack harness), G3 (RAG eval in CI and review queue), G4 and G5 (desk and human gate), G6 (one scorecard across all three).

## What is in the repo now

```
corpus/      synthetic policy files in nine formats, deliberately messy
  official/      current terms (v3) and the official fees PDF
  superseded/    old terms (v2)
  drafts/        an unpublished Word draft
  notes/         meeting notes
  emails/        a staff email
  spreadsheets/  a Finance working sheet with a hidden tab
  scans/         a scanned page and a phone photo (OCR needed)
eval/        the traps list, scoring rules and 40-question core golden set
```

Planned: `rag/`, `mcp/`, `multiagent/`, `supabase/`, `docs/` and CI workflows, then layers for evals, observability, security, governance and AWS.

## Tests were written before the code

The traps list and the answer key were committed before any code existed. These commits are in my earlier repo, `arcaence-labs`, and their dates are the evidence:

| Commit (17:28 to 17:48 IST, 11 Nov 2026) | What it added |
|---|---|
| [bf42eae](https://github.com/saurabhsmahajan/arcaence-labs/commit/bf42eae) | Current terms of service (v3) |
| [5cda8ac](https://github.com/saurabhsmahajan/arcaence-labs/commit/5cda8ac) | Superseded v2, meeting notes, staff email |
| [7339152](https://github.com/saurabhsmahajan/arcaence-labs/commit/7339152) | Word draft, fees PDF, fees working sheet |
| [0d3ec48](https://github.com/saurabhsmahajan/arcaence-labs/commit/0d3ec48) | Scanned page and phone photo |
| [083ace1](https://github.com/saurabhsmahajan/arcaence-labs/commit/083ace1) | Core golden set and traps list |

## Known limits (stated up front)

No real customers or traffic, one reviewer instead of a team, no legal review of what the bot may say, and test cases written by me. The goal is a tested prototype with a clear gap list, not a claim of production readiness.

## Rules for this repo

- Synthetic data only.
- No secrets in commits. Copy `.env.example` to `.env` and fill it in locally; `.env` is ignored.

## Architecture

The architecture is built in versions, one file per version, plus a log of every decision. Each version has a plain-language explanation at the bottom for readers new to the project.

| Version | Date | What it shows |
| --- | --- | --- |
| [v0.1 Foundations](docs/architecture/v0.1-foundations.md) | 11 Nov 2026 | Corpus, evaluation set and database connection. The RAG pipeline is planned. |
| [v0.2 Ingestion](docs/architecture/v0.2-ingestion.md) | 12 Nov 2026 | Loaders for every format, OCR, one record per file, duplicate check, findings log. |
| [v0.3 Chunking and routing](docs/architecture/v0.3-chunking-and-routing.md) | 13 Nov 2026 | Clause-level chunks, local embeddings, vector index, price and policy routing. Status filter and answers are planned. |
| [v0.4 Cited answers and evaluation](docs/architecture/v0.4-cited-answers-and-evaluation.md) | 13 Nov 2026 | Cited answers with a code verifier, status filter before ranking, additive routing, golden-set scorer and saved baseline |
| [v0.5 Structured answers and verified retry](docs/architecture/v0.5-structured-answers-and-verified-retry.md) | 14 Nov 2026 | Schema-constrained answers, one verifier gating every answer, bounded retry with feedback, safe refusal, structured_v1 results |
| [v0.6 Failure diagnosis and the statute tier](docs/architecture/v0.6-failure-diagnosis-and-statute-tier.md) | 17 Nov 2026 | Three diagnosed retrieval failures, pointer expansion, statute tier, strict refusal, probe and recall tools, full run 76/76 |
| [v0.7 Access control and frozen contracts](docs/architecture/v0.7-access-control-and-frozen-contracts.md) | 18 Nov 2026 | Customer tables with row-level security, one guarded door to the policy knowledge, locked knowledge tables, frozen clause ids and answer schema, simulated-login tests, gate G1 met |
| [v0.8 MCP read tools and a launch-fixed role](docs/architecture/v0.8-mcp-read-tools-and-launch-fixed-role.md) | 19 Nov 2026 | An MCP server with three read tools, a read-only database login, PII masking in the server, a role fixed at launch, four layers that refuse a write, and a stdio done check |
| [v0.9 MCP write tools, dry run, token, cap and audit](docs/architecture/v0.9-mcp-write-tools-dry-run-token-cap-audit.md) | 20 Nov 2026 | Two write tools offered only to a write role, a dry run and a single-use token bound to the arguments, a cumulative refund cap, a required policy clause, a server-owned write schema and an append-only audit log. |
| [v0.10 MCP privacy tools, policy server, resource and prompt](docs/architecture/v0.10-mcp-privacy-tools-policy-server-resource-prompt.md) | 21 Nov 2026 | Privacy requests that only a person can finish, a deletion process enforced by the database with a 7-day cooling-off, a counts-only export, a narrow accessibility door, a separate policy server with its own login, and a refund-limits resource and investigation prompt built from one source. |
| [v0.11 MCP attack harness and Inspector evidence](docs/architecture/v0.11-attack-harness-and-inspector-evidence.md) | 22 Nov 2026 | 32 attacks in six families against the real servers, a pass rule that needs a refusal and unchanged tables, three fixed defects (non-ASCII ids, odd amounts, a date-time schema bug) and the evidence for gate G2. |
| [v0.12 Phase 3 evals, the desk pipeline and the CI gate](docs/architecture/v0.12-phase-3-evals-desk-pipeline-and-ci-gate.md) | 23 Nov 2026 | A classifier that sorts vague, hostile and multi-part messages before retrieval, a desk that answers, asks, escalates or answers in parts, fixed text for risky sentences, rule-based scoring with an unsupported-claim rate that fell from 23.3% to 0.0%, and a GitHub Actions gate with a read-only database login. |

Decisions and their trade-offs: [decisions.md](docs/architecture/decisions.md).

## Notes

Study notes written as each part of the build is completed. Each concept is explained in plain language, with why it is needed, how it was built here, and the architect's view.

| Day | Notes | Covers |
| --- | --- | --- |
| Day 1 (11 Nov) | [Foundations](docs/notes/day-01-foundations.md) | Workflow vs agent, RAG, source authority, loaders, embeddings, structured data, clause IDs, evaluation first, controls, engineering foundations. |
| Day 2 (12 Nov) | [Ingestion hardening](docs/notes/day-02-ingestion.md) | Faithful extraction, prompt injection, OCR, one record contract, duplicates, findings as tests. |
| Day 3 (13 Nov) | [Chunking, embeddings and routing](docs/notes/day-03-chunking-embeddings-routing.md) | Chunking, clause IDs and the registry, embeddings, vector index, repeatable loading, routing by data type, similarity versus authority, prices kept out of vectors. |
| Day 4 (13 Nov) | [Cited answers, verification and the first baseline](docs/notes/day-04-cited-answers-verification-baseline.md) | Grounded answers, code verifier, status filter, hybrid routing, golden-set baseline and after-fix numbers |
| Day 5 (14 Nov) | [Structured answers, verification and retry](docs/notes/day-05-structured-answers-verification-retry.md) | Answer schema, refusal as a field, one verifier reused, bounded retry with feedback, safe refusal, stub-model tests, structured_v1 results and their caveats |
| Day 6 (17 Nov) | [Retrieval failures, diagnosis and fixes](docs/notes/day-06-retrieval-failures-diagnosis-fixes.md) | Failure families, probing, recall without a model, status filter, pointer expansion, statute tier, characterization tests, collateral effects, strict refusal, full run 76/76 |
| Day 7 (18 Nov) | [Access control, the guarded door and frozen contracts](docs/notes/day-07-access-control-guarded-door-contracts.md) | Row-level security, roles that bypass it, security-definer helper, the guarded door, least privilege, simulated-login tests, frozen reference test, contracts and drift test. |
| Day 8 (19 Nov) | [MCP read tools, masking and a fixed role](docs/notes/day-08-mcp-read-tools-masking-fixed-role.md) | MCP servers and tool contracts, a read-only database role, least privilege, defence in depth, PII masking, schema validation, role fixed at launch, fail closed, and three real 2025 incidents behind the decisions. |
| Day 9 (20 Nov) | [MCP write tools, dry run, single-use token, cap and audit](docs/notes/day-09-mcp-write-tools-dry-run-token-cap-audit.md) | Write tools versus read tools, dry run, single-use token bound to the arguments, cumulative cap, clause required, audit log, server-owned write database, savepoints, advisory lock, replay, fail closed, and four real cases behind the decisions. |
| Day 10 (21 Nov) | [Privacy tools, policy server, resource and prompt](docs/notes/day-10-privacy-tools-policy-server-resource-and-prompt.md) | Privacy requests that a person must finish, human approval and a 7-day cooling-off, a deletion process enforced by the database, counts-only export, a narrow security-definer door, a separate policy server, tools versus resources versus prompts, and three real cases behind the decisions. |
| Day 11 (22 Nov) | [Attack harness, Inspector evidence and gate G2](docs/notes/day-11-attack-harness-inspector-evidence-and-gate-g2.md) | Adversarial testing, the refused-and-unchanged pass rule, KNOWN gaps, ASCII-only input, output schema as a contract, client versus server checks, and three real cases behind the decisions. |
| Day 12 (23 Nov) | [Phase 3 evals, the desk pipeline and the CI gate](docs/notes/day-12-phase-3-evals-the-desk-pipeline-and-the-ci-gate.md) | Versioned golden sets, a classifier with a safe fallback, fixed text for risky sentences, parts answers, deterministic scoring and the unsupported-claim rate, judges kept on a leash with a blind check, dev versus holdout, a CI gate with a least-privilege login, and real cases (Air Canada, Chevrolet, tj-actions) behind the decisions. |

Findings from the ingestion work: [phase-1-ingestion.md](docs/build-logs/phase-1-ingestion.md).

Findings from the Phase 2 work (in progress): [phase-2-answering.md](docs/build-logs/phase-2-answering.md).

Findings from the RAG Phase 3 work: [rag-phase-3-evals-and-desk.md](docs/build-logs/rag-phase-3-evals-and-desk.md).

## Blogs

Posts on the Arcaence blog that tell this project as a story. Each link is added when the post is published.

| # | Post | Status |
| --- | --- | --- |
| 1 | [Define Good Before You Build: The Test Is the Requirements Document](https://www.arcaence.com/p/define-good-before-you-build-the) | Published |
| 2 | [What a RAG system must know before it answers](https://www.arcaence.com/p/what-a-rag-system-must-know-before) | Published |
