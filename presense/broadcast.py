"""Latest-state WebSocket broadcast, bounded to one pending snapshot."""
import asyncio
import json


class StateBroadcaster:
    def __init__(self):
        self.latest = None
        self.clients = set()
        self.pending = asyncio.Queue(maxsize=1)

    @property
    def client_count(self):
        return len(self.clients)

    def submit(self, snapshot):
        self.latest = json.dumps(snapshot, ensure_ascii=False)
        if self.pending.full():
            self.pending.get_nowait()
        self.pending.put_nowait(self.latest)

    async def register(self, ws):
        self.clients.add(ws)
        try:
            if self.latest is not None:
                await ws.send(self.latest)
            await ws.wait_closed()
        finally:
            self.clients.discard(ws)

    async def _send(self, ws, payload):
        try:
            await asyncio.wait_for(ws.send(payload), timeout=1)
        except Exception:
            self.clients.discard(ws)
            try:
                await asyncio.wait_for(ws.close(), timeout=1)
            except Exception:
                pass

    async def pump(self):
        while True:
            payload = await self.pending.get()
            await asyncio.gather(*(self._send(ws, payload) for ws in tuple(self.clients)))
