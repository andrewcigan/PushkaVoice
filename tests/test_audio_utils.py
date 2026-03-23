"""Tests for utils/audio_utils.py."""
import pytest

from utils.audio_utils import get_wav_duration


class TestGetWavDuration:
    def test_returns_correct_duration(self, sample_wav):
        duration = get_wav_duration(sample_wav)
        assert abs(duration - 0.5) < 0.01

    def test_zero_length_wav(self, tmp_path):
        import wave
        import numpy as np

        wav_path = str(tmp_path / "empty.wav")
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"")

        assert get_wav_duration(wav_path) == 0.0

    def test_longer_wav(self, tmp_path):
        import wave
        import numpy as np

        wav_path = str(tmp_path / "long.wav")
        sr = 16000
        duration = 3.0
        audio = np.zeros(int(sr * duration), dtype=np.int16)
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(audio.tobytes())

        result = get_wav_duration(wav_path)
        assert abs(result - 3.0) < 0.01

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            get_wav_duration("/nonexistent/file.wav")
