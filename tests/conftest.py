"""Shared fixtures for PushkaVoice tests."""
import json
import struct
import sys
import wave
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

# ── Mock macOS-only modules before any app code imports them ──
# These modules are unavailable on Linux where tests run.

_mock_modules = {
    "AppKit": MagicMock(),
    "Quartz": MagicMock(),
    "objc": MagicMock(),
    "rumps": MagicMock(),
    "Foundation": MagicMock(),
    "Cocoa": MagicMock(),
    "pyobjc": MagicMock(),
    "gigaam": MagicMock(),
    "webview": MagicMock(),
}
for mod_name, mock in _mock_modules.items():
    if mod_name not in sys.modules:
        sys.modules[mod_name] = mock

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def tmp_config_path(tmp_path):
    """Return a temporary path for settings.json."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir / "settings.json"


@pytest.fixture
def make_config(tmp_config_path, monkeypatch):
    """Create a Config instance with a temporary config file."""
    import utils.config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_config_path)

    from utils.config import Config
    return Config


@pytest.fixture
def config(make_config):
    """A default Config instance."""
    return make_config()


@pytest.fixture
def sample_wav(tmp_path):
    """Create a short sample WAV file (0.5s of silence at 16kHz)."""
    wav_path = str(tmp_path / "2024-01-15_14-30-00.wav")
    sample_rate = 16000
    duration = 0.5
    n_samples = int(sample_rate * duration)
    audio = np.zeros(n_samples, dtype=np.int16)

    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio.tobytes())

    return wav_path


@pytest.fixture
def sample_wav_with_text(sample_wav):
    """Create a WAV file with an accompanying .txt file."""
    txt_path = sample_wav.replace(".wav", ".txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("Привет мир")
    return sample_wav


@pytest.fixture
def mock_transcriber():
    """A mock Transcriber that is 'ready' and returns fixed text."""
    t = MagicMock()
    t.is_ready = True
    t.is_loading = False
    t.transcribe.return_value = "тестовый текст для транскрипции"
    return t


@pytest.fixture
def mock_recorder(monkeypatch):
    """Patch AudioRecorder so it doesn't use real audio hardware."""
    mock_sd = MagicMock()
    monkeypatch.setitem(sys.modules, "sounddevice", mock_sd)
    mock_sd.query_devices.return_value = {
        "name": "Test Mic",
        "max_input_channels": 1,
        "default_samplerate": 16000.0,
    }
    return mock_sd
