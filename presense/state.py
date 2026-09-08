"""Single event-loop owned caption state; predictions never enter ASR history."""
from collections import deque
from dataclasses import dataclass
import time
import uuid


@dataclass
class Utterance:
    id: int
    at: float
    text: str
    translation: str = ""


class CaptionState:
    def __init__(self, window=60, cold_start=5, ttl=4, clock=time.monotonic):
        if not 30 <= window <= 60 or cold_start < 0 or ttl <= 0:
            raise ValueError("window must be 30–60 seconds; invalid cold_start or TTL")
        self.clock, self.window, self.cold_start, self.ttl = clock, window, cold_start, ttl
        self.session = uuid.uuid4().hex
        self.history = deque(maxlen=200)
        self.started = clock()
        self.revision = self.utterance_id = self.sequence = 0
        self.live = self.live_translation = self.prediction = self.prediction_translation = ""
        self.prediction_at = None
        self.live_at = None
        self.context_note = {}
        self.status = "Listening · 建立上下文"
        self.resolution = ""

    def prune(self):
        while self.history and self.clock() - self.history[0].at > self.window:
            self.history.popleft()

    def clear_prediction(self, reason=""):
        self.prediction = self.prediction_translation = ""
        self.prediction_at = None
        self.context_note = {}
        if reason:
            self.resolution = reason

    def partial(self, text):
        text = text.strip()[:4000]
        if text == self.live:
            return False
        self.live_at = self.clock()
        self.live, self.live_translation = text, ""
        self.revision += 1
        self.clear_prediction("revised" if self.prediction else "")
        return True

    def final(self, text):
        text = text.strip()[:4000]
        if not text:
            return None
        self.prune()
        self.utterance_id += 1
        self.history.append(Utterance(self.utterance_id, self.clock(), text))
        self.revision += 1
        self.live = self.live_translation = ""
        self.live_at = None
        # Only real final ASR supplies confirmed text, never model guesses.
        self.clear_prediction("replaced_by_final_asr")
        return self.utterance_id

    def set_translation(self, utterance_id, text):
        self.prune()
        for item in self.history:
            if item.id == utterance_id:
                item.translation = text
                return True
        return False

    def ready(self):
        self.prune()
        return (self.clock() - self.started >= self.cold_start and
                bool(self.history) and len(self.live.split()) >= 4)

    def request(self):
        self.prune()
        return {"revision": self.revision, "live": self.live,
                "history": [u.text for u in self.history][-30:]}

    def apply(self, revision, result):
        if revision != self.revision or not self.live:
            return False
        self.live_translation = result.get("live_translation", "")
        self.clear_prediction()
        if self.ready() and result.get("prediction"):
            self.resolution = "pending"
            self.prediction = result["prediction"]
            self.prediction_translation = result.get("prediction_translation", "")
            self.prediction_at = self.clock()
            self.context_note = {"topic": result.get("topic", ""),
                                 "key_concepts": result.get("key_concepts", []),
                                 "recent_idea": result.get("recent_idea", "")}
        return True

    def expire(self):
        changed = False
        if self.prediction_at is not None and self.clock() - self.prediction_at >= self.ttl:
            self.clear_prediction("expired")
            changed = True
        if self.live_at is not None and self.clock() - self.live_at >= 15:
            self.partial("")
            self.live_at = None
            changed = True
        return changed

    def snapshot(self):
        self.prune()
        self.sequence += 1
        last = self.history[-1] if self.history else None
        return {"protocol": "presense.v0", "session_id": self.session,
                "sequence": self.sequence, "revision": self.revision,
                "confirmed": last.text if last else "", "live": self.live,
                "prediction": self.prediction,
                "confirmed_translation": last.translation if last else "",
                "live_translation": self.live_translation,
                "prediction_translation": self.prediction_translation,
                "original": last.text if last else "",
                "translated": last.translation if last else "",
                "context": self.context_note, "status": self.status,
                "prediction_resolution": self.resolution}
