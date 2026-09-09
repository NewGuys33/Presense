import unittest
import numpy as np
from presense.audio_context import install_audio_context, new_words

class Recorder:
    def __init__(self):
        self.calls = []
    def perform_final_transcription(self, audio_bytes=None, use_prompt=True, word_timestamps=None):
        self.calls.append(audio_bytes.copy())
        self.last_transcription_metadata = {'words': [
            {'word': ' very', 'start': 0, 'end': .5},
            {'word': ' very', 'start': 1.6, 'end': 1.9}]}
        return 'very very'

class ContextTests(unittest.TestCase):
    def test_audio_prefix_and_repeated_new_word(self):
        r = Recorder()
        install_audio_context(r)
        r.perform_final_transcription(np.ones(32000))
        self.assertEqual(r.perform_final_transcription(np.full(16000, 2)), 'very')
        self.assertEqual(len(r.calls[-1]), 40000)
        self.assertTrue(np.all(r.calls[-1][:24000] == 1))
        self.assertTrue(np.all(r.calls[-1][24000:] == 2))
        self.assertEqual(r.early_transcription_on_silence, 0)
    def test_bad_metadata(self):
        self.assertIsNone(new_words(None, 1))
        self.assertIsNone(new_words({'words': [{'word':'x', 'start':float('nan'), 'end':1}]}, 1))
    def test_disabled(self):
        r = Recorder()
        install_audio_context(r, 0)
        self.assertFalse(hasattr(r, '_presense_audio_context'))
    def test_fallback(self):
        class Missing(Recorder):
            def perform_final_transcription(self, audio_bytes=None, use_prompt=True, word_timestamps=None):
                self.calls.append(audio_bytes.copy())
                self.last_transcription_metadata = None
                return 'current'
        r = Missing()
        install_audio_context(r)
        r.perform_final_transcription(np.ones(32000))
        self.assertEqual(r.perform_final_transcription(np.ones(16000)), 'current')
        self.assertEqual([len(a) for a in r.calls], [32000,40000,16000])
