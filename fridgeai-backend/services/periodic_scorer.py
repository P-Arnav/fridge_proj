"""
periodic_scorer.py — Re-scores all scored items every hour so that
RSL/P_spoil/paif_action stay current as time passes.

Only items that have already been scored (p_spoil IS NOT NULL) are
re-scored; unscored items are still handled by the settle_timer.
"""
from __future__ import annotations
import asyncio
import logging

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
RESCORE_INTERVAL = 3600  # 1 hour


async def _run_loop() -> None:
    while True:
        await asyncio.sleep(RESCORE_INTERVAL)
        try:
            await _rescore_all()
        except Exception as exc:
            logger.exception("periodic_scorer error: %s", exc)


async def _rescore_all() -> None:
    from core.database import get_db
    from services.scorer import run_for_item

    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT item_id FROM items WHERE p_spoil IS NOT NULL"
        )

    item_ids = [row["item_id"] for row in rows]
    if not item_ids:
        return

    logger.info("periodic_scorer: re-scoring %d item(s)", len(item_ids))
    for item_id in item_ids:
        await run_for_item(item_id)


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_run_loop())
        logger.info("Periodic scorer started (interval=%ds)", RESCORE_INTERVAL)


def stop() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        _task = None
        logger.info("Periodic scorer stopped")
