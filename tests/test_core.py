import asyncio
import json
from pathlib import Path
import threading
import unittest

from presense.state import CaptionState
from presense.pipeline import Pipeline
from presense.predictor import validate_result
from presense.broadcast import StateBroadcaster
from presense.demo import run_demo
from bootstrap import patch_main, OLD, TRANSLATOR_OLD


class Clock:
    def __init__(self): self.now = 0
    def __call__(self): return self.now


class StateTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.state = CaptionState(clock=self.clock)
        self.state.final("Increasing alpha delays conduction.")
        self.state.partial("When the firing angle increases")

    def result(self):
        return {"prediction": "output voltage decreases", "prediction_translation": "电压降低"}

    def test_cold_start_gates_prediction(self):
        self.state.apply(self.state.revision, self.result())
        self.assertEqual(self.state.prediction, "")
        self.clock.now = 6
        self.state.apply(self.state.revision, self.result())
        self.assertNotEqual(self.state.prediction, "")

    def test_prediction_never_becomes_evidence(self):
        self.clock.now = 6
        self.state.apply(self.state.revision, self.result())
        self.state.final("When the firing angle increases the current remains unchanged.")
        self.assertEqual(self.state.prediction, "")
        self.assertIn("current remains unchanged", self.state.snapshot()["confirmed"])
        self.assertNotIn("output voltage decreases", str(self.state.request()["history"]))

    def test_late_response_discarded_after_revision_and_final(self):
        self.clock.now = 6
        revision = self.state.revision
        self.state.partial("When the firing angle decreases")
        self.assertFalse(self.state.apply(revision, self.result()))
        revision = self.state.revision
        self.state.final("The voltage is unchanged.")
        self.assertFalse(self.state.apply(revision, self.result()))

    def test_prediction_expires_without_more_audio(self):
        self.clock.now = 6
        self.state.apply(self.state.revision, self.result())
        self.clock.now = 11
        self.assertTrue(self.state.expire())
        self.assertEqual(self.state.prediction, "")

    def test_rolling_context_expiry_prevents_prediction(self):
        self.clock.now = 61
        self.assertFalse(self.state.ready())
        self.assertEqual(self.state.request()["history"], [])

    def test_out_of_order_translation_keeps_pairing(self):
        first = self.state.utterance_id
        second = self.state.final("A different statement.")
        self.state.set_translation(second, "另一句话")
        self.state.set_translation(first, "前一句")
        self.assertEqual(self.state.snapshot()["confirmed_translation"], "另一句话")

    def test_repeated_identical_final_is_a_new_utterance(self):
        a = self.state.final("Yes.")
        b = self.state.final("Yes.")
        self.assertNotEqual(a, b)

    def test_reset_session_has_new_identity(self):
        other = CaptionState(clock=self.clock)
        self.assertNotEqual(other.session, self.state.session)
        self.assertEqual(other.snapshot()["confirmed"], "")

    def test_malformed_model_output_rejected(self):
        for value in ("not JSON", "[]", '{"prediction": 3}', '{"key_concepts": "wrong"}'):
            with self.assertRaises(ValueError): validate_result(value)

    def test_patch_requires_exactly_one_hook(self):
        patched = patch_main("f(\n" + OLD + "\n)\n" + TRANSLATOR_OLD)
        self.assertIn("on_realtime_transcription_update=self._on_live", patched)
        with self.assertRaises(ValueError): patch_main(OLD + OLD)
        with self.assertRaises(ValueError): patch_main("unrelated source")


class AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_final_clears_prediction_while_network_is_pending(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def predict(req):
            entered.set()
            await release.wait()
            return {"prediction": "stale guessed continuation"}
        async def translate(text): return "译文：" + text
        emitted = []
        pipeline = Pipeline(predict, translate, emitted.append,
                            state=CaptionState(cold_start=0), interval=0.2)
        pipeline.start()
        try:
            pipeline.final("Context for our lecture.")
            pipeline.partial("When the firing angle increases")
            await asyncio.wait_for(entered.wait(), 1)
            pipeline.final("When the firing angle increases, current stays constant.")
            release.set()
            await asyncio.sleep(0.1)
            self.assertEqual(pipeline.state.prediction, "")
            self.assertIn("current stays constant", pipeline.state.snapshot()["confirmed"])
        finally:
            await pipeline.close()
        pipeline.partial("must not appear after stopping")
        self.assertEqual(pipeline.state.live, "")

    async def test_translation_backlog_is_bounded(self):
        async def predict(req): return {}
        async def translate(text): return text
        p = Pipeline(predict, translate, lambda s: None)
        for i in range(100): p.final(str(i))
        self.assertEqual(p.finals.qsize(), 20)
        self.assertEqual(p.state.snapshot()["confirmed"], "99")

    async def test_reconnecting_client_receives_current_snapshot(self):
        from websockets.asyncio.server import serve
        from websockets.asyncio.client import connect
        broadcaster = StateBroadcaster()
        broadcaster.submit({"protocol": "presense.v0", "confirmed": "Hello", "prediction": ""})
        async with serve(broadcaster.register, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            for _ in range(2):
                async with connect(f"ws://127.0.0.1:{port}") as ws:
                    message = json.loads(await asyncio.wait_for(ws.recv(), 1))
                    self.assertEqual(message["confirmed"], "Hello")

    async def test_demo_has_live_prediction_and_actual_correction(self):
        stop, emitted = threading.Event(), []
        def emit(snapshot):
            emitted.append(snapshot)
            if "conduction period becomes shorter" in snapshot["confirmed"]:
                stop.set()
        await asyncio.wait_for(run_demo(emit, stop, port=0, speed=20), 2)
        self.assertTrue(any(x["live"] for x in emitted))
        self.assertTrue(any(x["prediction"] for x in emitted))
        self.assertEqual(emitted[-1]["prediction"], "")
        self.assertIn("conduction period becomes shorter", emitted[-1]["confirmed"])


if __name__ == "__main__":
    unittest.main()
