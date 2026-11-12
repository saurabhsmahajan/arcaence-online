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
| RAG (ingestion, grounding, access control, evals, service) | Not started |
| MCP server | Not started |
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

Decisions and their trade-offs: [decisions.md](docs/architecture/decisions.md).

## Notes

Study notes written as each part of the build is completed. Each concept is explained in plain language, with why it is needed, how it was built here, and the architect's view.

| Day | Notes | Covers |
| --- | --- | --- |
| Day 1 (11 Nov) | [Foundations](docs/notes/day-01-foundations.md) | Workflow vs agent, RAG, source authority, loaders, embeddings, structured data, clause IDs, evaluation first, controls, engineering foundations. |
| Day 2 (12 Nov) | [Ingestion hardening](docs/notes/day-02-ingestion.md) | Faithful extraction, prompt injection, OCR, one record contract, duplicates, findings as tests. |

Findings from the ingestion work: [phase-1-ingestion.md](docs/build-logs/phase-1-ingestion.md).

## Blogs

Posts on the Arcaence blog that tell this project as a story. Each link is added when the post is published.

| # | Post | Status |
| --- | --- | --- |
| 1 | [Define Good Before You Build: The Test Is the Requirements Document](https://www.arcaence.com/p/define-good-before-you-build-the) | Published |
