from __future__ import annotations
import logging
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}  # household_id -> set[WebSocket]
        self._ws_household: dict[WebSocket, str] = {}      # reverse lookup

    def connect(self, ws: WebSocket, household_id: str = "__default__") -> None:
        if household_id not in self._connections:
            self._connections[household_id] = set()
        self._connections[household_id].add(ws)
        self._ws_household[ws] = household_id
        total = sum(len(s) for s in self._connections.values())
        logger.info("WS client connected [%s] — total: %d", household_id, total)

    def disconnect(self, ws: WebSocket) -> None:
        household_id = self._ws_household.pop(ws, None)
        if household_id and household_id in self._connections:
            self._connections[household_id].discard(ws)
            if not self._connections[household_id]:
                del self._connections[household_id]
        total = sum(len(s) for s in self._connections.values())
        logger.info("WS client disconnected — total: %d", total)

    @property
    def client_count(self) -> int:
        return sum(len(s) for s in self._connections.values())

    async def broadcast(self, message: dict, household_id: str | None = None) -> None:
        """If household_id is given, only send to that household. Otherwise broadcast to all."""
        if household_id is not None:
            targets = list(self._connections.get(household_id, set()))
        else:
            targets = [ws for conns in self._connections.values() for ws in conns]

        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except (WebSocketDisconnect, RuntimeError):
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


# Singleton shared across the whole application
manager = ConnectionManager()
