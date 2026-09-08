"""Explicit scripted fixture, NOT an AI prediction benchmark."""
import asyncio
from .state import CaptionState
from .broadcast import StateBroadcaster


async def run_demo(emit, stop, port=8765, speed=1):
    from websockets.asyncio.server import serve
    state = CaptionState(cold_start=0)
    broadcaster = StateBroadcaster()

    def publish():
        state.status = "DEMO · 固定脚本，无真实音频或 AI 调用"
        snapshot = state.snapshot()
        broadcaster.submit(snapshot)
        emit(snapshot)

    async def delay(seconds):
        for _ in range(max(1, int(seconds / speed * 20))):
            if stop.is_set():
                return False
            await asyncio.sleep(0.05)
        return True

    pump = asyncio.create_task(broadcaster.pump())
    try:
        async with serve(broadcaster.register, "127.0.0.1", port):
            publish()
            while not stop.is_set():
                uid = state.final("Increasing the firing angle delays conduction.")
                state.set_translation(uid, "增大触发角会延迟导通。")
                publish()
                if not await delay(2): break
                state.partial("When the firing angle increases")
                publish()
                if not await delay(1): break
                state.apply(state.revision, {
                    "live_translation": "当触发角增大时",
                    "prediction": "the average output voltage may decrease.",
                    "prediction_translation": "平均输出电压可能降低。"})
                publish()
                if not await delay(2): break
                uid = state.final("When the firing angle increases, the conduction period becomes shorter.")
                state.set_translation(uid, "当触发角增大时，导通时间变短。")
                publish()
                if not await delay(3): break
    finally:
        state.partial("")
        state.clear_prediction("stopped")
        state.status = "Demo stopped"
        emit(state.snapshot())
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
