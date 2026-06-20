from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from sec_insider_db.database.models import SecBackfillState


async def get_or_create_backfill_state(session: AsyncSession) -> SecBackfillState:
    state = await session.get(SecBackfillState, 1)
    if state is None:
        state = SecBackfillState(id=1, backfill_complete=False)
        session.add(state)
        await session.flush()
    return state


async def checkpoint_backfill(
    session: AsyncSession,
    *,
    year: int,
    quarter: int,
    accession_number: str | None,
) -> SecBackfillState:
    state = await get_or_create_backfill_state(session)
    state.last_year = year
    state.last_quarter = quarter
    state.last_accession = accession_number
    state.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return state


async def mark_backfill_complete(session: AsyncSession) -> SecBackfillState:
    state = await get_or_create_backfill_state(session)
    state.backfill_complete = True
    state.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return state
