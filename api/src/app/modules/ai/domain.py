from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Namespace = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]


class AIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EntityInput(AIModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    kind: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)] = (
        "concept"
    )


class FactInput(AIModel):
    subject: EntityInput
    predicate: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    object: EntityInput
    evidence: str = Field(min_length=1, max_length=200)

    @field_validator("evidence")
    @classmethod
    def require_nonblank_evidence(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence cannot be blank")
        return value


class DocumentInput(AIModel):
    namespace: Namespace = "default"
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=12_000)
    facts: list[FactInput] = Field(default_factory=list[FactInput], max_length=32)

    @model_validator(mode="after")
    def require_evidence(self) -> Self:
        if not self.title.strip() or not self.text.strip():
            raise ValueError("title and text cannot be blank")
        for fact in self.facts:
            if fact.evidence not in self.text:
                raise ValueError("each fact requires exact evidence present in the document")
        return self


class Chunk(AIModel):
    id: UUID
    document_id: UUID
    namespace: str
    title: str
    text: str
    position: int


class StoredFact(AIModel):
    id: UUID
    subject_id: UUID
    subject: str
    subject_kind: str
    predicate: str
    object_id: UUID
    object: str
    object_kind: str
    evidence: str
    chunk_id: UUID
    document_id: UUID
    namespace: str


class PreparedDocument(AIModel):
    id: UUID
    namespace: str
    title: str
    content_hash: str
    chunks: list[Chunk]
    facts: list[StoredFact]


class VectorHit(AIModel):
    chunk_id: UUID
    document_id: UUID
    score: float


class GraphContext(AIModel):
    chunks: list[Chunk] = Field(default_factory=list[Chunk])
    facts: list[StoredFact] = Field(default_factory=list[StoredFact])


class QueryInput(AIModel):
    namespace: Namespace = "default"
    question: str = Field(min_length=1, max_length=2_000)
    limit: int = Field(default=4, ge=1, le=8)

    @model_validator(mode="after")
    def require_question(self) -> Self:
        if not self.question.strip():
            raise ValueError("question cannot be blank")
        return self


class SourceResponse(AIModel):
    reference: str
    chunk_id: UUID
    document_id: UUID
    title: str
    text: str


class QueryResponse(AIModel):
    answer: str
    sources: list[SourceResponse]
    facts: list[StoredFact]


class DocumentStatus(AIModel):
    document_id: UUID
    namespace: str
    status: str
    chunk_count: int
    collection: str
