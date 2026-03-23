"""Tests for core/recorder.py."""
import sys
import wave
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def mock_sounddevice(monkeypatch):
    """Mock sounddevice module."""
    mock_sd = MagicMock()
    mock_sd.query_devices.return_value = {
        "name": "Test Mic",
        "max_input_channels": 2,
        "default_samplerate": 48000.0,
    }
    monkeypatch.setitem(sys.modules, "sounddevice", mock_sd)
    # Force reimport
    if "core.recorder" in sys.modules:
        del sys.modules["core.recorder"]
    return mock_sd


class TestAudioRecorderInit:
    def test_default_init(self):
        from core.recorder import AudioRecorder
        r = AudioRecorder()
        assert r.device_id is None
        assert r.target_sample_rate == 16000
        assert r._frames == []
        assert r._recording is False

    def test_custom_device_and_rate(self):
        from core.recorder import AudioRecorder
        r = AudioRecorder(device_id=3, sample_rate=44100)
        assert r.device_id == 3
        assert r.target_sample_rate == 44100


class TestResample:
    def test_same_rate_no_change(self):
        from core.recorder import AudioRecorder
        r = AudioRecorder()
        data = np.array([[1], [2], [3], [4]], dtype=np.int16)
        result = r._resample(data, 16000, 16000)
        np.testing.assert_array_equal(result, data)

    def test_downsample_reduces_length(self):
        from core.recorder import AudioRecorder
        r = AudioRecorder()
        data = np.arange(48000, dtype=np.int16).reshape(-1, 1)
        result = r._resample(data, 48000, 16000)
        assert len(result) == 16000

    def test_upsample_increases_length(self):
        from core.recorder import AudioRecorder
        r = AudioRecorder()
        data = np.arange(16000, dtype=np.int16).reshape(-1, 1)
        result = r._resample(data, 16000, 48000)
        assert len(result) == 48000

    def test_output_is_int16(self):
        from core.recorder import AudioRecorder
        r = AudioRecorder()
        data = np.arange(100, dtype=np.int16).reshape(-1, 1)
        result = r._resample(data, 100, 200)
        assert result.dtype == np.int16


class TestGetNativeSampleRate:
    def test_default_device(self, mock_sounddevice):
        from core.recorder import AudioRecorder
        r = AudioRecorder()
        rate = r._get_native_sample_rate()
        assert rate == 48000
        mock_sounddevice.query_devices.assert_called_with(kind='input')

    def test_specific_device(self, mock_sounddevice):
        from core.recorder import AudioRecorder
        r = AudioRecorder(device_id=5)
        rate = r._get_native_sample_rate()
        assert rate == 48000
        mock_sounddevice.query_devices.assert_called_with(5)


class TestListDevices:
    def test_returns_input_devices(self, mock_sounddevice):
        mock_sounddevice.query_devices.return_value = [
            {"name": "Mic 1", "max_input_channels": 1, "default_samplerate": 44100.0},
            {"name": "Speaker", "max_input_channels": 0, "default_samplerate": 48000.0},
            {"name": "Mic 2", "max_input_channels": 2, "default_samplerate": 16000.0},
        ]
        from core.recorder import AudioRecorder
        devices = AudioRecorder.list_devices()
        assert len(devices) == 2
        assert devices[0]["name"] == "Mic 1"
        assert devices[1]["name"] == "Mic 2"

    def test_device_has_required_fields(self, mock_sounddevice):
        mock_sounddevice.query_devices.return_value = [
            {"name": "Mic", "max_input_channels": 1, "default_samplerate": 44100.0},
        ]
        from core.recorder import AudioRecorder
        devices = AudioRecorder.list_devices()
        d = devices[0]
        assert "id" in d
        assert "name" in d
        assert "channels" in d
        assert "sample_rate" in d


class TestStopRecording:
    def test_stop_no_frames_returns_empty(self):
        from core.recorder import AudioRecorder
        r = AudioRecorder()
        r._recording = True
        r._native_sr = 16000
        result = r.stop()
        assert result == ""

    def test_stop_saves_wav(self, tmp_path):
        from core.recorder import AudioRecorder
        r = AudioRecorder()
        r._recording = True
        r._native_sr = 16000
        r._frames = [np.zeros((1600, 1), dtype=np.int16)]

        wav_path = r.stop(save_dir=str(tmp_path))
        assert wav_path.endswith(".wav")

        with wave.open(wav_path, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000

    def test_stop_resamples_if_needed(self, tmp_path):
        from core.recorder import AudioRecorder
        r = AudioRecorder(sample_rate=16000)
        r._recording = True
        r._native_sr = 48000  # different from target
        r._frames = [np.zeros((4800, 1), dtype=np.int16)]

        wav_path = r.stop(save_dir=str(tmp_path))
        with wave.open(wav_path, "rb") as wf:
            assert wf.getframerate() == 16000
