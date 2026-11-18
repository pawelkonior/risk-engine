from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.http.dependencies import DatabaseSession
from app.modules.items import service
from app.modules.items.schemas import ItemCreate, ItemPage, ItemResponse, ItemUpdate

router = APIRouter(prefix="/items", tags=["items"])


@router.post("", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(payload: ItemCreate, session: DatabaseSession) -> ItemResponse:
    """Create a public example item."""
    return ItemResponse.model_validate(await service.create_item(session, payload))


@router.get("", response_model=ItemPage)
async def list_items(
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ItemPage:
    return await service.list_items(session, limit=limit, offset=offset)


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(item_id: UUID, session: DatabaseSession) -> ItemResponse:
    return ItemResponse.model_validate(await service.get_item(session, item_id))


@router.patch("/{item_id}", response_model=ItemResponse)
async def update_item(item_id: UUID, payload: ItemUpdate, session: DatabaseSession) -> ItemResponse:
    return ItemResponse.model_validate(await service.update_item(session, item_id, payload))


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: UUID, session: DatabaseSession) -> Response:
    await service.delete_item(session, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
