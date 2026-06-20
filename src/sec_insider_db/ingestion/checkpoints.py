from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from sec_insider_db.database.models import SecBackfillState


def get_or_create_backfill_state(session: Session) -> SecBackfillState:
    state = session.get(SecBackfillState, 1)
    if state is None:
        state = SecBackfillState(id=1, backfill_complete=False)
        session.add(state)
        session.flush()
    return state


def checkpoint_backfill(
    session: Session,
    *,
    year: int,
    quarter: int,
    accession_number: str | None,
) -> SecBackfillState:
    state = get_or_create_backfill_state(session)
    state.last_year = year
    state.last_quarter = quarter
    state.last_accession = accession_number
    state.updated_at = datetime.now(timezone.utc)
    session.flush()
    return state


def mark_backfill_complete(session: Session) -> SecBackfillState:
    state = get_or_create_backfill_state(session)
    state.backfill_complete = True
    state.updated_at = datetime.now(timezone.utc)
    session.flush()
    return state
