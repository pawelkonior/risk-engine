from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, Field(max_length=10_000)]


class ItemCreate(BaseModel):
    """Input for the public example resource."""

    model_config = ConfigDict(extra="forbid")
    title: Title
    description: Description | None = None


class ItemUpdate(BaseModel):
    """PATCH fields; a title may be omitted but cannot be null."""

    model_config = ConfigDict(extra="forbid")
    title: Title | None = None
    description: Description | None = None

    @model_validator(mode="after")
    def validate_update(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("provide at least one field")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be null")
        return self


class ItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    id: UUID
    title: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class ItemPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ItemResponse]
    limit: int
    offset: int
    has_more: bool
