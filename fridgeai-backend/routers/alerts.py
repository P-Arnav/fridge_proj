from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends
import asyncpg

from core.database import db_dependency
from models.alerts import AlertRead
from routers.auth import get_household_id

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertRead])
async def list_alerts(
    since: Optional[str] = None,
    limit: int = 100,
    household_id: str = Depends(get_household_id),
    conn: asyncpg.Connection = Depends(db_dependency),
):
    query = "SELECT * FROM alerts WHERE dismissed = 0 AND household_id = $1"
    params: list = [household_id]

    if since:
        params.append(since)
        query += f" AND created_at >= ${len(params)}"

    params.append(limit)
    query += f" ORDER BY created_at DESC LIMIT ${len(params)}"

    rows = await conn.fetch(query, *params)
    return [AlertRead.from_row(r) for r in rows]


@router.delete("/{alert_id}")
async def dismiss_alert(
    alert_id: str,
    household_id: str = Depends(get_household_id),
    conn: asyncpg.Connection = Depends(db_dependency),
):
    await conn.execute(
        "UPDATE alerts SET dismissed = 1 WHERE alert_id = $1 AND household_id = $2",
        alert_id, household_id,
    )
    return {"ok": True}


@router.delete("")
async def clear_all_alerts(
    household_id: str = Depends(get_household_id),
    conn: asyncpg.Connection = Depends(db_dependency),
):
    result = await conn.execute(
        "UPDATE alerts SET dismissed = 1 WHERE dismissed = 0 AND household_id = $1",
        household_id,
    )
    return {"ok": True, "cleared": int(result.split()[-1])}
