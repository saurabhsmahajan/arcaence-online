"""What the policy tool returns."""
from pydantic import BaseModel, ConfigDict


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PolicyHit(Out):
    citation: str          # for example "tos_v3 2.2": the label an answer must cite
    doc_id: str
    clause_id: str | None  # None for text that has no clause number
    score: float           # similarity, higher is closer
    content: str


class PolicySearch(Out):
    results: list[PolicyHit]
    note: str
