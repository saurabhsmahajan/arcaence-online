# Frozen contracts

Two things in AOP are contracts, not implementation details, because other parts depend on them: the **clause ids** and the **answer schema**. The verifier, the golden set and the structured answer already depend on them, and the MCP server and the agents will too.

| File | What it freezes |
| --- | --- |
| `clause_ids_vN.csv` | Every `(doc_id, clause_id)` pair in the clause registry when version N was frozen |
| `answer_schema_vN.json` | The exact JSON schema of an answer: `answer`, `citations`, `refused`, `refusal_reason` |

The latest version of each file is the contract. Older versions stay as history.

## What may change freely

- Adding clauses or documents. New clause ids are allowed and are only reported by the test.
- `section_ref` and `topic` in the registry. They describe a clause and are not part of its identity.
- The answer prompt, the model, retrieval and the retry loop, as long as the schema is unchanged.

## What may not change without a new version

- Renaming or removing a frozen `(doc_id, clause_id)`. A citation that used it would stop resolving.
- Any change to the answer schema: a field added, removed, renamed or made optional.

## How to change a contract on purpose

1. Write an ADR in `docs/architecture/decisions.md` saying what changes and why.
2. Run `uv run python scripts\freeze_contracts.py --version N` from `rag` for the next N. It refuses to overwrite an existing version.
3. Update the golden set and any caller that depends on the old shape.
4. Run `uv run python test_contracts.py`. It must pass against the new latest version.

`rag/test_contracts.py` fails when the live registry loses a frozen id or when `SCHEMA` in `rag/answer.py` differs from the latest frozen schema.
