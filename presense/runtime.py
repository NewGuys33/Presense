"""Adapter to pinned CaptionSystem; retains WASAPI, final ASR and translation."""
import asyncio
import copy
import math
import sys
from pathlib import Path
from .state import CaptionState
from .pipeline import Pipeline
from .predictor import SemanticPredictor
from .broadcast import StateBroadcaster


def load_upstream():
    root = Path(__file__).resolve().parents[1]
    vendor = root / "vendor" / "realtime-caption"
    if not (vendor / "main.py").exists():
        raise RuntimeError("Run setup_presense.bat first")
    # Regenerate the adapter when updating an existing installation. No config overwrite.
    from bootstrap import verify, patch_main
    verify(vendor / "main.py")
    (vendor / "presense_upstream.py").write_text(
        patch_main((vendor / "main.py").read_text(encoding="utf-8")), encoding="utf-8")
    sys.path.insert(0, str(vendor))
    import presense_upstream
    return presense_upstream


def build_system(upstream, config, device, emit, status):
    # Short caption chunks by default, including installations with an older
    # config.yaml. Override presense.segment_pause_seconds to tune the pause;
    # null retains the original vad.post_speech_silence_duration setting.
    config = copy.deepcopy(config)
    pause = config.get("presense", {}).get("segment_pause_seconds", 0.35)
    if pause is not None:
        pause = float(pause)
        if not math.isfinite(pause) or not 0.2 <= pause <= 2.0:
            raise ValueError("presense.segment_pause_seconds must be between 0.2 and 2.0 seconds")
        config.setdefault("vad", {})["post_speech_silence_duration"] = pause

    class PresenseSystem(upstream.CaptionSystem):
        def __init__(self):
            super().__init__(config, device, config["whisper"]["model"],
                             on_ready=lambda: status("Listening · 系统音频已就绪"),
                             on_realtime_error_external=status)
            self.pipeline = None
            self._broadcaster = StateBroadcaster()
            # Bound legacy translation requests; the worker already serializes them.
            if hasattr(self._translator, "_client"):
                self._translator._client = self._translator._client.with_options(timeout=8, max_retries=0)

        def _on_live(self, text):
            if self._loop and not self._loop.is_closed() and not self._stop_event.is_set():
                self._loop.call_soon_threadsafe(self._partial, text)

        def _partial(self, text):
            if self.pipeline:
                self.pipeline.partial(text)

        def _on_transcription(self, text):
            if self._loop and not self._loop.is_closed() and not self._stop_event.is_set():
                self._loop.call_soon_threadsafe(self._final, text)

        def _final(self, text):
            if self.pipeline:
                self.pipeline.final(text)

        def prepare(self):
            super().prepare()
            if self._recorder is not None:
                from .audio_context import install_audio_context
                install_audio_context(
                    self._recorder,
                    config.get("presense", {}).get("audio_context_seconds", 1.5),
                    status,
                )
            if self._recorder is None:
                status("ASR 初始化失败；请查看控制台，检查模型下载和依赖")
                self._stop_event.set()
                if self._loop and self._stop_event_async:
                    self._loop.call_soon_threadsafe(self._stop_event_async.set)

        async def run(self):
            p = config.get("presense", {})
            local = config.get("translation", {}).get("translation_model") == "ollama"
            if local:
                from .local_model import LocalModel
                opts = config.get("ollama", {})
                predictor = LocalModel(model=opts.get("model", "qwen2.5:3b"),
                                       base_url=opts.get("base_url", "http://127.0.0.1:11434"),
                                       timeout=opts.get("timeout_seconds", 30))
                try:
                    await predictor.check()
                except Exception as exc:
                    status(str(exc))
                    await predictor.close()
                    raise
            else:
                predictor = SemanticPredictor(config["openai"]["api_key"], p.get("prediction_model", "gpt-4o-mini"))
            state = CaptionState(window=p.get("context_seconds", 60),
                                 cold_start=p.get("cold_start_seconds", 5),
                                 ttl=p.get("prediction_ttl_seconds", 4))

            def publish(snapshot):
                self._broadcaster.submit(snapshot)
                emit(snapshot)

            async def translate(text):
                if local:
                    return await predictor.translate(text)
                return await asyncio.to_thread(self._translator.translate, text)

            self.pipeline = Pipeline(predictor, translate, publish, state=state,
                                     interval=p.get("prediction_interval", 1.2))
            self.pipeline.start()
            pump = asyncio.create_task(self._broadcaster.pump())
            try:
                await super().run()
            finally:
                await self.pipeline.close()
                pump.cancel()
                await asyncio.gather(pump, return_exceptions=True)
                await predictor.close()

    return PresenseSystem()
