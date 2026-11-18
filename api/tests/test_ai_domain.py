from unittest.mock import create_autospec
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.modules.ai import router
from app.modules.ai.domain import DocumentInput, EntityInput, FactInput
from app.modules.ai.service import AiService, prepare_document


def fact_payload() -> dict[str, object]:
    return {
        "subject": {"name": "Warszawa", "kind": "city"},
        "predicate": "capital_of",
        "object": {"name": "Polska", "kind": "country"},
        "evidence": "Warszawa jest stolicą Polski.",
    }


@pytest.mark.parametrize("field", ["name", "kind"])
@pytest.mark.parametrize("value", ["", " ", "\t\n"])
def test_entity_names_and_kinds_reject_blank_values(field: str, value: str) -> None:
    values = {"name": "Warszawa", "kind": "city", field: value}
    with pytest.raises(ValidationError):
        EntityInput.model_validate(values)


def test_entity_strings_strip_before_length_validation_and_default_kind_is_preserved() -> None:
    entity = EntityInput(name=" \tWarszawa\n ", kind=" city ")
    assert entity.name == "Warszawa"
    assert entity.kind == "city"
    assert EntityInput(name=" A ").kind == "concept"
    assert EntityInput(name=f" {'x' * 120} ").name == "x" * 120


@pytest.mark.parametrize("field", ["predicate", "evidence"])
@pytest.mark.parametrize("value", ["", " ", "\t\n"])
def test_facts_reject_blank_predicates_and_evidence(field: str, value: str) -> None:
    values = fact_payload()
    values[field] = value
    with pytest.raises(ValidationError):
        FactInput.model_validate(values)


def test_fact_normalization_preserves_exact_evidence_and_source_citation() -> None:
    values = fact_payload()
    values["subject"] = {"name": " Warszawa ", "kind": " city "}
    values["predicate"] = " capital_of "
    values["object"] = {"name": " Polska ", "kind": " country "}
    values["evidence"] = " Warszawa jest stolicą Polski. "
    fact = FactInput.model_validate(values)
    assert fact.predicate == "capital_of"
    assert fact.evidence == " Warszawa jest stolicą Polski. "
    source = DocumentInput(title="T", text=f"Początek.{fact.evidence}Koniec.", facts=[fact])
    prepared = prepare_document(uuid4(), source)
    assert prepared.facts[0].subject == "Warszawa"
    assert prepared.facts[0].subject_kind == "city"
    assert prepared.facts[0].object == "Polska"
    assert prepared.facts[0].object_kind == "country"
    assert prepared.facts[0].evidence == fact.evidence
    assert prepared.facts[0].evidence in prepared.chunks[0].text


def test_evidence_whitespace_is_not_normalized_to_a_different_source_substring() -> None:
    values = fact_payload()
    values["evidence"] = " Warszawa jest stolicą Polski. "
    fact = FactInput.model_validate(values)
    with pytest.raises(ValidationError, match="exact evidence"):
        DocumentInput(title="T", text="Warszawa jest stolicą Polski.", facts=[fact])


@pytest.mark.parametrize(
    "subject,object_value,predicate,evidence",
    [
        ({"name": " ", "kind": "city"}, {"name": "Polska"}, "capital_of", "Warszawa"),
        ({"name": "Warszawa", "kind": " "}, {"name": "Polska"}, "capital_of", "Warszawa"),
        ({"name": "Warszawa"}, {"name": " "}, "capital_of", "Warszawa"),
        ({"name": "Warszawa"}, {"name": "Polska", "kind": " "}, "capital_of", "Warszawa"),
        ({"name": "Warszawa"}, {"name": "Polska"}, " ", "Warszawa"),
        ({"name": "Warszawa"}, {"name": "Polska"}, "capital_of", " "),
    ],
)
async def test_invalid_fact_inputs_return_422_before_indexing(
    test_settings: Settings,
    subject: dict[str, str],
    object_value: dict[str, str],
    predicate: str,
    evidence: str,
) -> None:
    service = create_autospec(AiService, instance=True)
    application = create_app(test_settings)
    application.dependency_overrides[router.service] = lambda: service
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.put(
            f"/api/v1/ai/documents/{uuid4()}",
            json={
                "title": "T",
                "text": "Warszawa jest stolicą Polski.",
                "facts": [
                    {
                        "subject": subject,
                        "predicate": predicate,
                        "object": object_value,
                        "evidence": evidence,
                    }
                ],
            },
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    service.ingest.assert_not_awaited()
