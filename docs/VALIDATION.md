# Validation — 2026-09-08

Environment: Linux / Python; no Windows audio device or AI API key supplied.

Passed:

- 14 unittest tests: state transitions, cold start, history expiry, prediction TTL,
  final-ASR authority, repeated utterance IDs, late translation pairing,
  stale inference response, bounded translation queue, malformed model output,
  patch contract, WebSocket reconnect, scripted demo correction.
- 7-second headless CLI demo: Live → Prediction → final replacement → clean exit.
- Syntax parse of every Python project file and the actual patched upstream main.py.
- Pinned upstream main.py Git blob SHA matches 70966dc1c04940060d2045d47ef39b4db430984d.
- Extracted actual upstream prepare() executed with a fake recorder; confirmed
  enable_realtime_transcription=True, use_microphone=False for loopback and live callback delivery.

Not run:

- Windows full install and baseline audio capture.
- Real Whisper model loading, speech recognition timing or CPU load.
- OpenAI/DeepL network requests or prediction accuracy measurements.
- Tk desktop visual QA (no display server in this environment).

Do not interpret simulated test passes as G1–G5 real-world acceptance.
