from __future__ import annotations
import asyncio
from typing import Any
from fastapi import WebSocket

class SocketHub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.clients.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.clients.discard(websocket)

    async def _send_json(self, client: WebSocket, message: dict[str, Any]) -> bool:
        try:
            await asyncio.wait_for(client.send_json(message), timeout=0.35)
            return True
        except Exception:
            return False

    async def broadcast_message(self, message: dict[str, Any]) -> None:
        clients = list(self.clients)
        if not clients:
            return
        results = await asyncio.gather(*(self._send_json(client, message) for client in clients))
        stale = [client for client, ok in zip(clients, results) if not ok]
        for client in stale:
            self.disconnect(client)

