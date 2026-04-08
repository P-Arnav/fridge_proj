from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends
import asyncpg
from pydantic import BaseModel

from core.database import db_dependency

router = APIRouter(prefix="/restock", tags=["restock"])


class RestockSuggestion(BaseModel):
    name: str
    category: str
    reason: str
    priority: str  # "urgent" | "low_stock"
    current_qty: Optional[int] = None
    rsl: Optional[float] = None
    p_spoil: Optional[float] = None


@router.get("", response_model=list[RestockSuggestion])
async def get_restock_suggestions(conn: asyncpg.Connection = Depends(db_dependency)):
    """
    Suggest items to restock based on current pantry state:
    - Urgent: RSL < 2 days and P_spoil > 0.5 (will go bad before you can restock)
    - Low stock: quantity == 1 and P_spoil > 0.4 (running out while spoiling)
    - Overdue: consumption pattern predicts item was needed >1 day ago (not already suggested)
    """
    rows = await conn.fetch(
        "SELECT name, category, quantity, rsl, p_spoil FROM items"
    )

    suggestions: list[RestockSuggestion] = []
    seen: set[str] = set()

    for row in rows:
        name = row["name"]
        category = row["category"]
        qty = row["quantity"]
        rsl = row["rsl"]
        p_spoil = row["p_spoil"]

        if name.lower() in seen:
            continue

        if rsl is not None and rsl < 2.0 and p_spoil is not None and p_spoil > 0.5:
            suggestions.append(RestockSuggestion(
                name=name,
                category=category,
                reason=f"Expires in {rsl:.1f} day(s) — replace soon",
                priority="urgent",
                current_qty=qty,
                rsl=rsl,
                p_spoil=p_spoil,
            ))
            seen.add(name.lower())

        elif qty == 1 and p_spoil is not None and p_spoil > 0.4:
            suggestions.append(RestockSuggestion(
                name=name,
                category=category,
                reason="Only 1 left and spoiling",
                priority="low_stock",
                current_qty=qty,
                rsl=rsl,
                p_spoil=p_spoil,
            ))
            seen.add(name.lower())

    # Check consumption history for items overdue based on buying cadence.
    # Covers items already in inventory AND items that may have run out.
    overdue_rows = await conn.fetch(
        """
        WITH lagged AS (
            SELECT
                LOWER(item_name) AS item_key,
                item_name,
                category,
                consumed_at::timestamp AS ts,
                EXTRACT(EPOCH FROM (
                    consumed_at::timestamp
                    - LAG(consumed_at::timestamp) OVER (
                        PARTITION BY LOWER(item_name)
                        ORDER BY consumed_at::timestamp
                    )
                )) / 86400.0 AS interval_days
            FROM consumption_history
            WHERE reason != 'wasted'
        ),
        aggregated AS (
            SELECT
                item_key,
                MAX(item_name)     AS name,
                MAX(category)      AS category,
                COUNT(*)           AS times_consumed,
                MAX(ts)            AS last_consumed,
                AVG(interval_days) AS avg_interval_days
            FROM lagged
            GROUP BY item_key
        )
        SELECT
            item_key, name, category, times_consumed, last_consumed, avg_interval_days,
            avg_interval_days - EXTRACT(EPOCH FROM (NOW() - last_consumed)) / 86400.0
                AS predicted_next_days
        FROM aggregated
        WHERE times_consumed >= 2
          AND avg_interval_days IS NOT NULL
          AND avg_interval_days - EXTRACT(EPOCH FROM (NOW() - last_consumed)) / 86400.0 < -1.0
        """
    )

    # Build a quick lookup of what's currently in the pantry
    current_stock = {row["name"].lower() for row in rows}

    for row in overdue_rows:
        key = row["item_key"]
        if key in seen:
            continue
        overdue_by = abs(float(row["predicted_next_days"]))
        suggestions.append(RestockSuggestion(
            name=row["name"],
            category=row["category"],
            reason=f"Based on your usage pattern, you're overdue to restock by {overdue_by:.1f} day(s)",
            priority="low_stock" if key in current_stock else "urgent",
            current_qty=None,
            rsl=None,
            p_spoil=None,
        ))
        seen.add(key)

    # Sort: urgent first, then by highest P_spoil
    suggestions.sort(key=lambda s: (0 if s.priority == "urgent" else 1, -(s.p_spoil or 0)))
    return suggestions
