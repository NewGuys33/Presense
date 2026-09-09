"""Bounded acoustic context for final ASR, without displaying the prefix twice."""
import inspect
import math
import threading
import time


def new_words(metadata, boundary):
    """Assign boundary-straddling words by midpoint; never dedupe by spelling."""
    words = (metadata or {}).get('words')
    if not isinstance(words, list) or not words:
        return None
    result = []
    for item in words:
        try:
            start, end = float(item['start']), float(item['end'])
            word = item['word']
            if not isinstance(word, str) or not math.isfinite(start + end) or end < start:
                return None
        except (KeyError, TypeError, ValueError):
            return None
        if (start + end) / 2 >= boundary:
            result.append(word)
    return ''.join(result).strip()


def install_audio_context(recorder, seconds=1.5, status=lambda text: None):
    """Reuse the recorder's existing final model; no additional GPU model.

    Supported RealtimeSTT exposes word_timestamps on perform_final_transcription.
    Unsupported versions keep ordinary final recognition and report that fact.
    """
    seconds = float(seconds)
    if not math.isfinite(seconds) or not 0 <= seconds <= 3:
        raise ValueError('presense.audio_context_seconds must be between 0 and 3')
    if seconds == 0 or getattr(recorder, '_presense_audio_context', False):
        return
    original = getattr(recorder, 'perform_final_transcription', None)
    if original is None or 'word_timestamps' not in inspect.signature(original).parameters:
        status('当前 RealtimeSTT 不支持上下文去重所需时间戳；继续普通识别')
        return
    import numpy as np
    # Early requests contain unextended audio and cannot be reused for this path.
    recorder.early_transcription_on_silence = 0
    lock = threading.Lock()
    tail = None
    last_at = 0.0
    warned = False

    def contextual(audio_bytes=None, use_prompt=True, word_timestamps=None):
        nonlocal tail, last_at, warned
        with lock:
            current = np.asarray(recorder.audio if audio_bytes is None else audio_bytes).copy()
            if current.ndim != 1 or current.size == 0:
                tail = None
                return original(audio_bytes, use_prompt=use_prompt, word_timestamps=word_timestamps)
            # RealtimeSTT's final audio is normalized mono at 16 kHz.
            prefix = tail if time.monotonic() - last_at < 8 else None
            boundary = 0 if prefix is None else prefix.size / 16000.0
            combined = current if prefix is None else np.concatenate((prefix, current))
            recorder.last_transcription_metadata = None
            try:
                text = original(combined, use_prompt=use_prompt, word_timestamps=True)
                if boundary and text:
                    trimmed = new_words(recorder.last_transcription_metadata, boundary)
                    if trimmed is None:
                        # Never publish an undeduplicated prefix if metadata is absent.
                        if not warned:
                            status('识别后端未返回词时间戳；本段回退普通识别')
                            warned = True
                        text = original(current, use_prompt=use_prompt, word_timestamps=word_timestamps)
                    else:
                        text = trimmed
                if getattr(recorder, 'interrupt_stop_event', None) is not None and recorder.interrupt_stop_event.is_set():
                    tail = None
                    return ''
                tail = current[-int(seconds * 16000):].copy()
                last_at = time.monotonic()
                return text
            except Exception:
                tail = None
                raise

    recorder.perform_final_transcription = contextual
    recorder._presense_audio_context = True
