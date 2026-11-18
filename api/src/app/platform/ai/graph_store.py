"""Neo4j knowledge and source graphs with explicit, parameterized Cypher."""

from itertools import pairwise
from typing import Protocol, TypedDict, cast
from uuid import UUID

from neo4j import AsyncDriver, AsyncManagedTransaction, AsyncSession
from pydantic import BaseModel, TypeAdapter

from app.core.errors import ConflictError
from app.modules.ai.domain import Chunk, GraphContext, PreparedDocument, StoredFact

_CONSTRAINTS = (
    "CREATE CONSTRAINT ai_document_identity IF NOT EXISTS "
    "FOR (n:Document) REQUIRE (n.namespace, n.id) IS UNIQUE",
    "CREATE CONSTRAINT ai_chunk_identity IF NOT EXISTS "
    "FOR (n:Chunk) REQUIRE (n.namespace, n.id) IS UNIQUE",
    "CREATE CONSTRAINT ai_entity_identity IF NOT EXISTS "
    "FOR (n:Entity) REQUIRE (n.namespace, n.id) IS UNIQUE",
    "CREATE CONSTRAINT ai_claim_identity IF NOT EXISTS "
    "FOR (n:Claim) REQUIRE (n.namespace, n.id) IS UNIQUE",
)

_DOCUMENT = """
MERGE (document:Document {namespace: $namespace, id: $document_id})
ON CREATE SET document.title = $title, document.content_hash = $content_hash
RETURN document.content_hash AS content_hash
"""

_CHUNKS = """
UNWIND $chunks AS item
MATCH (document:Document {namespace: $namespace, id: $document_id})
MERGE (chunk:Chunk {namespace: $namespace, id: item.id})
ON CREATE SET chunk.document_id = $document_id
WITH document, chunk, item WHERE chunk.document_id = $document_id
SET chunk.title = item.title, chunk.text = item.text, chunk.position = item.position
MERGE (document)-[:HAS_CHUNK]->(chunk)
RETURN count(chunk) AS count
"""

_NEXT = """
UNWIND $links AS link
MATCH (left:Chunk {namespace: $namespace, id: link.left, document_id: $document_id})
MATCH (right:Chunk {namespace: $namespace, id: link.right, document_id: $document_id})
MERGE (left)-[:NEXT]->(right)
"""

_FACTS = """
UNWIND $facts AS item
MATCH (document:Document {namespace: $namespace, id: $document_id})-[:HAS_CHUNK]->
      (chunk:Chunk {namespace: $namespace, id: item.chunk_id, document_id: $document_id})
MERGE (subject:Entity {namespace: $namespace, id: item.subject_id})
ON CREATE SET subject.name = item.subject, subject.kind = item.subject_kind
MERGE (object:Entity {namespace: $namespace, id: item.object_id})
ON CREATE SET object.name = item.object, object.kind = item.object_kind
MERGE (claim:Claim {namespace: $namespace, id: item.id})
ON CREATE SET claim.document_id = $document_id
WITH chunk, subject, object, claim, item WHERE claim.document_id = $document_id
SET claim += item
MERGE (subject)-[:SUBJECT_OF]->(claim)
MERGE (claim)-[:OBJECT]->(object)
MERGE (claim)-[:SUPPORTED_BY]->(chunk)
MERGE (chunk)-[:MENTIONS]->(subject)
MERGE (chunk)-[:MENTIONS]->(object)
RETURN count(claim) AS count
"""

_CONTEXT_CHUNKS = """
UNWIND $chunk_ids AS chunk_id
MATCH (document:Document {namespace: $namespace})-[:HAS_CHUNK]->
      (chunk:Chunk {namespace: $namespace, id: chunk_id})
WHERE document.id = chunk.document_id
RETURN properties(chunk) AS chunk
"""

_CONTEXT_FACTS = """
MATCH (document:Document {namespace: $namespace})-[:HAS_CHUNK]->
      (chunk:Chunk {namespace: $namespace})
MATCH (claim:Claim {namespace: $namespace})-[:SUPPORTED_BY]->(chunk)
MATCH (subject:Entity {namespace: $namespace})-[:SUBJECT_OF]->(claim)-[:OBJECT]->
      (object:Entity {namespace: $namespace})
WHERE chunk.id IN $chunk_ids AND document.id = chunk.document_id
  AND claim.document_id = document.id AND claim.chunk_id = chunk.id
  AND claim.subject_id = subject.id AND claim.object_id = object.id
RETURN DISTINCT properties(claim) AS fact ORDER BY fact.id LIMIT 32
"""

_DELETE = """
MATCH (document:Document {namespace: $namespace, id: $document_id})
OPTIONAL MATCH (document)-[:HAS_CHUNK]->(chunk:Chunk {namespace: $namespace})
WHERE chunk.document_id = $document_id
OPTIONAL MATCH (claim:Claim {namespace: $namespace, document_id: $document_id})
OPTIONAL MATCH (subject:Entity {namespace: $namespace})-[:SUBJECT_OF]->(claim)
OPTIONAL MATCH (claim)-[:OBJECT]->(object:Entity {namespace: $namespace})
OPTIONAL MATCH (chunk)-[:MENTIONS]->(mentioned:Entity {namespace: $namespace})
WITH document, collect(DISTINCT chunk) AS chunks, collect(DISTINCT claim) AS claims,
     collect(DISTINCT subject) + collect(DISTINCT object) + collect(DISTINCT mentioned) AS entities
FOREACH (claim IN claims | DETACH DELETE claim)
FOREACH (chunk IN chunks | DETACH DELETE chunk)
DETACH DELETE document
WITH entities
UNWIND entities AS entity
WITH DISTINCT entity WHERE NOT (entity)--()
DELETE entity
"""


class _HashRow(BaseModel):
    content_hash: str


class _CountRow(BaseModel):
    count: int


class _ChunkRow(BaseModel):
    chunk: Chunk


class _FactRow(BaseModel):
    fact: StoredFact


_CHUNK_ROWS = TypeAdapter(list[_ChunkRow])
_FACT_ROWS = TypeAdapter(list[_FactRow])


class _SessionDriver(Protocol):
    # Neo4j's runtime decorator leaves **config untyped in the public driver stubs.
    def session(self, *, database: str) -> AsyncSession: ...


class _DocumentParameters(TypedDict):
    namespace: str
    document_id: str


class Neo4jGraphStore:
    """Keep source provenance and knowledge in one portable Community/Aura database."""

    def __init__(self, driver: AsyncDriver, database: str) -> None:
        self._driver = cast(_SessionDriver, driver)
        self._database = database

    async def setup(self) -> None:
        async with self._driver.session(database=self._database) as session:
            for query in _CONSTRAINTS:
                result = await session.run(query)
                await result.consume()

    async def ping(self) -> None:
        async with self._driver.session(database=self._database) as session:
            result = await session.run("RETURN 1 AS ready")
            await result.consume()

    async def upsert(self, document: PreparedDocument) -> None:
        chunk_ids = {chunk.id for chunk in document.chunks}
        if (
            not document.chunks
            or len(chunk_ids) != len(document.chunks)
            or any(
                chunk.namespace != document.namespace or chunk.document_id != document.id
                for chunk in document.chunks
            )
            or any(
                fact.namespace != document.namespace
                or fact.document_id != document.id
                or fact.chunk_id not in chunk_ids
                for fact in document.facts
            )
        ):
            raise ValueError("document chunks and facts must belong to the document and namespace")
        async with self._driver.session(database=self._database) as session:
            await session.execute_write(self._upsert, document)

    @staticmethod
    async def _upsert(transaction: AsyncManagedTransaction, document: PreparedDocument) -> None:
        parameters: _DocumentParameters = {
            "namespace": document.namespace,
            "document_id": str(document.id),
        }
        result = await transaction.run(
            _DOCUMENT,
            **parameters,
            title=document.title,
            content_hash=document.content_hash,
        )
        row = await result.single(strict=True)
        stored = _HashRow.model_validate(dict(row))
        if stored.content_hash != document.content_hash:
            raise ConflictError("Document identity already exists with different content")
        result = await transaction.run(
            _CHUNKS,
            **parameters,
            chunks=[chunk.model_dump(mode="json") for chunk in document.chunks],
        )
        row = await result.single(strict=True)
        count = _CountRow.model_validate(dict(row))
        if count.count != len(document.chunks):
            raise ConflictError("A chunk identity already belongs to another document")
        ordered = sorted(document.chunks, key=lambda chunk: chunk.position)
        result = await transaction.run(
            _NEXT,
            **parameters,
            links=[
                {"left": str(left.id), "right": str(right.id)} for left, right in pairwise(ordered)
            ],
        )
        await result.consume()
        if document.facts:
            result = await transaction.run(
                _FACTS,
                **parameters,
                facts=[fact.model_dump(mode="json") for fact in document.facts],
            )
            row = await result.single(strict=True)
            count = _CountRow.model_validate(dict(row))
            if count.count != len(document.facts):
                raise ConflictError("A fact identity already belongs to another document")

    async def context(self, namespace: str, chunk_ids: list[UUID]) -> GraphContext:
        if not chunk_ids:
            return GraphContext()
        async with self._driver.session(database=self._database) as session:
            return await session.execute_read(self._context, namespace, chunk_ids)

    @staticmethod
    async def _context(
        transaction: AsyncManagedTransaction, namespace: str, chunk_ids: list[UUID]
    ) -> GraphContext:
        result = await transaction.run(
            _CONTEXT_CHUNKS, namespace=namespace, chunk_ids=[str(value) for value in chunk_ids]
        )
        rows = _CHUNK_ROWS.validate_python(await result.data())
        chunks = {row.chunk.id: row.chunk for row in rows}
        if any(
            chunk.namespace != namespace or chunk.id not in chunk_ids for chunk in chunks.values()
        ):
            raise ValueError("Neo4j returned a chunk outside the requested namespace")
        ordered = [chunks[value] for value in dict.fromkeys(chunk_ids) if value in chunks]
        if not ordered:
            return GraphContext()
        result = await transaction.run(
            _CONTEXT_FACTS, namespace=namespace, chunk_ids=[str(chunk.id) for chunk in ordered]
        )
        fact_rows = _FACT_ROWS.validate_python(await result.data())
        facts = [row.fact for row in fact_rows]
        if len(facts) > 32 or any(
            fact.namespace != namespace
            or fact.chunk_id not in chunks
            or fact.document_id != chunks[fact.chunk_id].document_id
            for fact in facts
        ):
            raise ValueError("Neo4j returned a fact without an owned source chunk")
        return GraphContext(chunks=ordered, facts=facts)

    async def delete(self, namespace: str, document_id: UUID) -> None:
        async with self._driver.session(database=self._database) as session:
            await session.execute_write(self._delete, namespace, document_id)

    @staticmethod
    async def _delete(
        transaction: AsyncManagedTransaction, namespace: str, document_id: UUID
    ) -> None:
        result = await transaction.run(_DELETE, namespace=namespace, document_id=str(document_id))
        await result.consume()
