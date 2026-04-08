from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
CHECK_INTERVAL = 3600  # 1 hour


async def _run_loop() -> None:
    while True:
        try:
            await _check_and_restock()
        except Exception as exc:
            logger.exception("auto_restock error: %s", exc)
        await asyncio.sleep(CHECK_INTERVAL)


async def _check_and_restock() -> None:
    from core.database import get_db
    from core.supabase_client import get_supabase
    from websocket.manager import manager

    # Find all households with auto-restock enabled
    try:
        sb = get_supabase()
        result = await sb.table("user_prefs").select("household_id").eq("auto_restock_enabled", True).execute()
        if not result.data:
            return
    except Exception:
        return  # Supabase unavailable — skip this cycle

    household_ids = list({row["household_id"] for row in result.data if row.get("household_id")})

    async with get_db() as conn:
        for household_id in household_ids:
            await _restock_for_household(conn, household_id, manager)


async def _restock_for_household(conn, household_id: str, manager) -> None:
    rows = await conn.fetch(
        "SELECT name, category, quantity, rsl, p_spoil FROM items WHERE household_id = $1",
        household_id,
    )
    now = datetime.now(tz=timezone.utc).isoformat()
    added: list[str] = []

    for row in rows:
        name, category, qty = row["name"], row["category"], row["quantity"]
        rsl, p_spoil = row["rsl"], row["p_spoil"]

        is_urgent = rsl is not None and rsl < 2.0 and p_spoil is not None and p_spoil > 0.5
        is_low = qty == 1 and p_spoil is not None and p_spoil > 0.4
        if not (is_urgent or is_low):
            continue

        # Skip if already in grocery list (unchecked) for this household
        existing = await conn.fetchrow(
            "SELECT grocery_id FROM grocery_items WHERE LOWER(name) = LOWER($1) AND checked = 0 AND household_id = $2",
            name, household_id,
        )
        if existing:
            continue

        grocery_id = str(uuid4())
        await conn.execute(
            "INSERT INTO grocery_items (grocery_id, household_id, name, category, quantity, checked, source, created_at) "
            "VALUES ($1,$2,$3,$4,1,0,'restock',$5)",
            grocery_id, household_id, name, category, now,
        )
        added.append(name)

    if added:
        await manager.broadcast({
            "event": "AUTO_RESTOCK",
            "timestamp": now,
            "data": {"added": added, "message": f"Auto-restocked: {', '.join(added)}"},
        }, household_id=household_id)
        logger.info("Auto-restock [%s] added %d item(s): %s", household_id, len(added), added)


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_run_loop())
        logger.info("Auto-restock service started (interval=%ds)", CHECK_INTERVAL)


def stop() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        _task = None
        logger.info("Auto-restock service stopped")
