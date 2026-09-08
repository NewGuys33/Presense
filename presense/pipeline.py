"""Bounded asynchronous workers: ASR updates never wait for cloud requests."""
import asyncio
from .state import CaptionState


class Pipeline:
    def __init__(self, predictor, translator, emit, *, state=None, interval=1.2):
        self.state = state or CaptionState()
        self.predictor, self.translator, self.emit = predictor, translator, emit
        self.interval = max(0.2, interval)
        self.finals = asyncio.Queue(maxsize=20)
        self.tasks = []
        self.closed = False
        self.live_source = self.live_result = ""
        self.live_uid = -1

    def start(self):
        self.tasks = [asyncio.create_task(self._predict()),
                      asyncio.create_task(self._translate()),
                      asyncio.create_task(self._translate_live()),
                      asyncio.create_task(self._expire())]
        self.publish()

    def publish(self):
        snap = self.state.snapshot()
        valid = (self.live_uid == self.state.utterance_id and self.live_source
                 and self.state.live.startswith(self.live_source))
        snap["live_translation"] = (
            self.live_result + (" ⟨后续内容翻译中…⟩" if self.state.live != self.live_source else "")
            if valid else ("翻译中…" if self.state.live else ""))
        self.emit(snap)

    def partial(self, text):
        if not self.closed and self.state.partial(text):
            self.publish()

    def final(self, text):
        if self.closed:
            return
        text = text.strip()[:4000]
        reuse = (self.live_uid == self.state.utterance_id and text == self.live_source
                 and bool(self.live_result))
        uid = self.state.final(text)
        if uid is None:
            return
        if reuse:
            self.state.set_translation(uid, self.live_result)
            self.publish()
            return
        if self.finals.full():
            self.finals.get_nowait()
            self.state.status = "翻译积压：跳过最旧待翻译项，原文保留"
        self.finals.put_nowait((uid, text))
        self.publish()

    async def _translate(self):
        while True:
            uid, text = await self.finals.get()
            try:
                result = await self.translator(text)
                self.state.set_translation(uid, result)
            except Exception as exc:
                self.state.status = "Translation error: " + type(exc).__name__
            self.publish()

    async def _translate_live(self):
        previous = None
        while True:
            await asyncio.sleep(0.3)
            text = self.state.live
            uid = self.state.utterance_id
            key = (uid, text)
            if not text or key == previous:
                continue
            # Single in-flight request; read the latest partial after each result.
            previous = key
            try:
                result = await self.translator(text)
                if uid == self.state.utterance_id and self.state.live.startswith(text):
                    self.live_uid, self.live_source, self.live_result = uid, text, result
                    self.publish()
                elif uid + 1 == self.state.utterance_id:
                    # The utterance finished while this translation was running.
                    # Promote only if the final ASR exactly matches its source.
                    row = self.state.transcript[-1] if self.state.transcript else None
                    if row and row.text == text and not row.translation:
                        self.state.set_translation(row.id, result)
                        self.publish()
            except Exception as exc:
                previous = None
                self.state.status = "Live translation error: " + type(exc).__name__
                self.publish()
                await asyncio.sleep(1)

    async def _predict(self):
        previous = -1
        while True:
            await asyncio.sleep(self.interval)
            req = self.state.request()
            if not req["live"] or req["revision"] == previous:
                continue
            previous = req["revision"]
            req["allow_prediction"] = self.state.ready()
            try:
                result = await self.predictor(req)
                if self.state.apply(req["revision"], result):
                    self.state.status = "Listening · 预测为未确认内容"
                    self.publish()
            except Exception as exc:
                self.state.status = "Prediction error: " + type(exc).__name__
                self.publish()

    async def _expire(self):
        while True:
            await asyncio.sleep(0.25)
            if self.state.expire():
                self.publish()

    async def close(self):
        self.closed = True
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.state.partial("")
        self.state.clear_prediction("stopped")
        self.state.status = "Stopped"
        self.publish()
