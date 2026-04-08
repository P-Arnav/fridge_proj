import logging

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from core.config import DEFAULT_HOUSEHOLD_ID
from websocket.manager import manager

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, client_type: str = "unknown", token: str = ""):
    await ws.accept()

    # Resolve household from token
    household_id = DEFAULT_HOUSEHOLD_ID
    if token:
        try:
            from routers.auth import _user_from_token
            user = await _user_from_token(token)
            household_id = user.household_id or DEFAULT_HOUSEHOLD_ID
        except Exception as exc:
            logger.warning("WS token validation failed: %s", exc)

    manager.connect(ws, household_id)
    await ws.send_json({
        "event": "WELCOME",
        "data": {
            "client_type": client_type,
            "connected_clients": manager.client_count,
        }
    })
    try:
        while True:
            # Keep connection alive; we only push from server
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
