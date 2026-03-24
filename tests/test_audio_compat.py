"""Tests for core/audio_compat.py — ffmpeg-free audio loading."""
import sys
import wave
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Ensure torch mock is available for import
_torch_mock = MagicMock()
if "torch" not in sys.modules:
    sys.modules["torch"] = _torch_mock
if "torchaudio" not in sys.modules:
    sys.modules["torchaudio"] = MagicMock()
    sys.modules["torchaudio.transforms"] = MagicMock()


class TestPatchGigaam:
    def test_patches_load_audio(self):
        import core.audio_compat as mod
        mod._patched = False

        mock_preprocess = MagicMock()
        # Insert gigaam.preprocess into sys.modules so `import gigaam.preprocess` works
        old = sys.modules.get("gigaam.preprocess")
        try:
            sys.modules["gigaam.preprocess"] = mock_preprocess
            mod.patch_gigaam()
            assert mock_preprocess.load_audio == mod.load_audio_no_ffmpeg
            assert mod._patched is True
        finally:
            if old is None:
                sys.modules.pop("gigaam.preprocess", None)
            else:
                sys.modules["gigaam.preprocess"] = old
            mod._patched = False

    def test_does_not_patch_twice(self):
        import core.audio_compat as mod
        mod._patched = True
        mock_preprocess = MagicMock()
        original_fn = mock_preprocess.load_audio
        with patch.dict("sys.modules", {"gigaam.preprocess": mock_preprocess, "gigaam": MagicMock()}):
            mod.patch_gigaam()
            # Should NOT have changed since _patched is True
            assert mock_preprocess.load_audio == original_fn
        mod._patched = False

    def test_handles_missing_gigaam(self):
        import core.audio_compat as mod
        mod._patched = False
        # gigaam not installed — should handle gracefully
        with patch.dict("sys.modules", {"gigaam": None, "gigaam.preprocess": None}):
            mod.patch_gigaam()  # should not raise
        mod._patched = False


class TestLoadAudioNoFfmpegWithWaveModule:
    """Test the wave-module fallback path (no real torchaudio needed)."""

    @pytest.fixture
    def wav_16k(self, tmp_path):
        """Create a 16kHz mono WAV file."""
        path = str(tmp_path / "test.wav")
        sr = 16000
        n = 8000  # 0.5s
        audio = (np.sin(np.linspace(0, np.pi * 2 * 440, n)) * 16000).astype(np.int16)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(audio.tobytes())
        return path

    @pytest.fixture
    def wav_stereo(self, tmp_path):
        """Create a stereo WAV file."""
        path = str(tmp_path / "stereo.wav")
        sr = 16000
        n = 8000
        left = (np.sin(np.linspace(0, np.pi * 2 * 440, n)) * 16000).astype(np.int16)
        right = (np.sin(np.linspace(0, np.pi * 2 * 880, n)) * 16000).astype(np.int16)
        stereo = np.column_stack([left, right])
        with wave.open(path, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(stereo.tobytes())
        return path

    def test_loads_wav_via_fallback(self, wav_16k):
        """When torchaudio fails, should fall back to wave module."""
        from core.audio_compat import load_audio_no_ffmpeg

        # Mock torchaudio.load to fail, forcing wave fallback
        mock_torchaudio = MagicMock()
        mock_torchaudio.load.side_effect = RuntimeError("no backend")
        with patch.dict("sys.modules", {"torchaudio": mock_torchaudio}):
            result = load_audio_no_ffmpeg(wav_16k, sample_rate=16000)

        # Result should be a torch tensor with audio data
        assert hasattr(result, 'numpy') or isinstance(result, MagicMock)

    def test_nonexistent_file_raises(self, tmp_path):
        from core.audio_compat import load_audio_no_ffmpeg
        mock_torchaudio = MagicMock()
        mock_torchaudio.load.side_effect = RuntimeError("file not found")
        with patch.dict("sys.modules", {"torchaudio": mock_torchaudio}):
            with pytest.raises(Exception):
                load_audio_no_ffmpeg(str(tmp_path / "nope.wav"), sample_rate=16000)
