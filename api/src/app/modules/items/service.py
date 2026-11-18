from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.items.models import Item
from app.modules.items.schemas import ItemCreate, ItemPage, ItemResponse, ItemUpdate


async def get_item(session: AsyncSession, item_id: UUID) -> Item:
    item = await session.get(Item, item_id)
    if item is None:
        raise NotFoundError("Item was not found")
    return item


async def list_items(session: AsyncSession, *, limit: int, offset: int) -> ItemPage:
    result = await session.scalars(
        select(Item).order_by(Item.created_at.desc(), Item.id).limit(limit + 1).offset(offset)
    )
    rows = list(result)
    return ItemPage(
        items=[ItemResponse.model_validate(item) for item in rows[:limit]],
        limit=limit,
        offset=offset,
        has_more=len(rows) > limit,
    )


async def create_item(session: AsyncSession, payload: ItemCreate) -> Item:
    item = Item(title=payload.title, description=payload.description)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def update_item(session: AsyncSession, item_id: UUID, payload: ItemUpdate) -> Item:
    item = await get_item(session, item_id)
    if payload.title is not None:
        item.title = payload.title
    if "description" in payload.model_fields_set:
        item.description = payload.description
    item.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(item)
    return item


async def delete_item(session: AsyncSession, item_id: UUID) -> None:
    item = await get_item(session, item_id)
    await session.delete(item)
    await session.commit()
