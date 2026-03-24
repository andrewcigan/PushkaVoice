"""Tests for core/audio_compat.py — ffmpeg-free audio loading via subprocess interception."""
import subprocess
import sys
import wave
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Ensure torch mock is available for import
if "torch" not in sys.modules:
    sys.modules["torch"] = MagicMock()
if "torchaudio" not in sys.modules:
    sys.modules["torchaudio"] = MagicMock()
    sys.modules["torchaudio.transforms"] = MagicMock()


class TestPatchGigaam:
    def test_patches_subprocess_run(self):
        import core.audio_compat as mod
        mod._patched = False
        original = subprocess.run

        try:
            mod.patch_gigaam()
            assert subprocess.run is not original
            assert subprocess.run is mod._patched_subprocess_run
            assert mod._patched is True
        finally:
            subprocess.run = original
            mod._patched = False

    def test_does_not_patch_twice(self):
        import core.audio_compat as mod
        mod._patched = True
        original = subprocess.run
        mod.patch_gigaam()
        # Should not have changed
        assert subprocess.run is original
        mod._patched = False

    def test_non_ffmpeg_commands_pass_through(self):
        import core.audio_compat as mod
        mod._patched = False
        original = subprocess.run

        try:
            mod.patch_gigaam()
            # Non-ffmpeg command should call original
            result = mod._patched_subprocess_run(
                ["echo", "hello"],
                capture_output=True, text=True
            )
            assert "hello" in result.stdout
        finally:
            subprocess.run = original
            mod._patched = False


class TestDecodeAudioWithoutFfmpeg:
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

    def test_intercepts_ffmpeg_wav(self, wav_16k):
        """Should decode WAV without actual ffmpeg."""
        from core.audio_compat import _decode_audio_without_ffmpeg

        cmd = [
            "ffmpeg", "-nostdin", "-threads", "0",
            "-i", wav_16k,
            "-f", "s16le", "-ac", "1", "-acodec", "pcm_s16le",
            "-ar", "16000", "-",
        ]

        # Mock torchaudio to force wave fallback
        mock_ta = MagicMock()
        mock_ta.load.side_effect = RuntimeError("no backend")
        with patch.dict("sys.modules", {"torchaudio": mock_ta}):
            result = _decode_audio_without_ffmpeg(cmd)

        assert result.returncode == 0
        assert len(result.stdout) > 0
        # Should be int16 PCM: 2 bytes per sample
        assert len(result.stdout) % 2 == 0

    def test_rejects_non_ffmpeg_cmd(self):
        from core.audio_compat import _decode_audio_without_ffmpeg
        with pytest.raises(FileNotFoundError):
            _decode_audio_without_ffmpeg(["ls", "-la"])

    def test_parses_sample_rate(self, wav_16k):
        """Should parse -ar flag for target sample rate."""
        from core.audio_compat import _decode_audio_without_ffmpeg

        cmd = ["ffmpeg", "-i", wav_16k, "-ar", "8000", "-f", "s16le", "-"]
        # Force wave fallback AND torchaudio resampler fallback
        # so it uses numpy interpolation
        mock_ta = MagicMock()
        mock_ta.load.side_effect = RuntimeError("no backend")
        mock_ta.transforms.Resample.side_effect = RuntimeError("no")
        with patch.dict("sys.modules", {"torchaudio": mock_ta}):
            result = _decode_audio_without_ffmpeg(cmd)

        # 0.5s at 8kHz = 4000 samples * 2 bytes = 8000 bytes
        assert 7000 < len(result.stdout) < 9000
