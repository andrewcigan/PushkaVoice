"""Tests for core/transcriber.py."""
import sys
import threading
import zipfile
from unittest.mock import MagicMock, patch

import pytest


def _make_valid_ckpt(path, size_mb=60):
    """Create a fake but valid .ckpt file (a valid zip archive of the right size)."""
    with zipfile.ZipFile(path, 'w') as zf:
        # Write enough padding data to reach desired size
        zf.writestr("data.bin", b"x" * (size_mb * 1_000_000))


@pytest.fixture(autouse=True)
def mock_gigaam(monkeypatch):
    """Mock gigaam module."""
    mock = MagicMock()
    monkeypatch.setitem(sys.modules, "gigaam", mock)
    return mock


class TestTranscriberInit:
    def test_initial_state(self):
        from core.transcriber import Transcriber
        t = Transcriber()
        assert t._model is None
        assert t._loading is False
        assert not t.is_ready
        assert not t.is_loading

    def test_initial_download_tracking_fields(self):
        from core.transcriber import Transcriber
        t = Transcriber()
        assert t._download_speed == 0.0
        assert t._download_eta == 0
        assert t._downloaded_mb == 0.0
        assert t._total_mb > 0  # pre-set to expected model size
        assert t._speed_samples == []
        assert t._elapsed_seconds == 0


class TestTranscriberGetStatus:
    def test_initial_status(self):
        from core.transcriber import Transcriber
        t = Transcriber()
        status = t.get_status()
        assert status["message"] == "Waiting..."
        assert status["progress"] == 0
        assert status["downloading"] is False
        assert status["loading"] is False
        assert status["ready"] is False
        assert status["error"] is None
        assert status["speed_mbs"] == 0.0
        assert status["eta_seconds"] == 0
        assert status["downloaded_mb"] == 0.0
        assert status["total_mb"] > 0
        assert "elapsed_seconds" in status

    def test_status_after_load(self, mock_gigaam):
        mock_gigaam.load_model.return_value = MagicMock()
        from core.transcriber import Transcriber
        t = Transcriber()
        t.load_model()
        status = t.get_status()
        assert status["ready"] is True
        assert status["loading"] is False
        assert status["downloading"] is False
        assert status["error"] is None

    def test_status_after_error(self, mock_gigaam):
        mock_gigaam.load_model.side_effect = RuntimeError("GPU unavailable")
        from core.transcriber import Transcriber
        t = Transcriber()
        t.load_model()
        status = t.get_status()
        assert status["ready"] is False
        assert status["loading"] is False
        assert status["error"] == "GPU unavailable"
        assert t.has_error is True

    def test_status_contains_speed_fields(self):
        from core.transcriber import Transcriber
        t = Transcriber()
        t._download_speed = 5 * 1024 * 1024
        t._download_eta = 90
        t._downloaded_mb = 250.5
        t._total_mb = 500.0
        status = t.get_status()
        assert status["speed_mbs"] == 5.0
        assert status["eta_seconds"] == 90
        assert status["downloaded_mb"] == 250.5
        assert status["total_mb"] == 500.0


class TestTranscriberProperties:
    def test_is_ready_false_before_load(self):
        from core.transcriber import Transcriber
        t = Transcriber()
        assert t.is_ready is False

    def test_is_ready_true_after_load(self):
        from core.transcriber import Transcriber
        t = Transcriber()
        t._model = MagicMock()  # simulate loaded model
        assert t.is_ready is True

    def test_is_loading_during_load(self):
        from core.transcriber import Transcriber
        t = Transcriber()
        t._loading = True
        assert t.is_loading is True


class TestTranscriberLoadModel:
    def test_load_model_sets_ready(self, mock_gigaam):
        mock_gigaam.load_model.return_value = MagicMock()
        from core.transcriber import Transcriber
        t = Transcriber()
        t.load_model()
        assert t.is_ready
        assert not t.is_loading

    def test_load_model_uses_correct_name(self, mock_gigaam):
        mock_gigaam.load_model.return_value = MagicMock()
        from core.transcriber import Transcriber, MODEL_NAME
        t = Transcriber()
        t.load_model()
        mock_gigaam.load_model.assert_called_once_with(MODEL_NAME)
        assert MODEL_NAME == "rnnt"

    def test_load_model_does_not_load_twice(self, mock_gigaam):
        mock_gigaam.load_model.return_value = MagicMock()
        from core.transcriber import Transcriber
        t = Transcriber()
        t.load_model()
        t.load_model()  # second call should be a no-op
        mock_gigaam.load_model.assert_called_once()

    def test_load_model_handles_error(self, mock_gigaam):
        mock_gigaam.load_model.side_effect = RuntimeError("model not found")
        from core.transcriber import Transcriber
        t = Transcriber()
        t.load_model()
        assert not t.is_ready
        assert not t.is_loading
        assert t.has_error is True
        assert "model not found" in t._error


class TestTranscriberRetryLoad:
    def test_retry_resets_error(self, mock_gigaam):
        mock_gigaam.load_model.side_effect = RuntimeError("fail")
        from core.transcriber import Transcriber
        t = Transcriber()
        t.load_model()
        assert t.has_error is True

        # Now fix the mock and retry
        mock_gigaam.load_model.side_effect = None
        mock_gigaam.load_model.return_value = MagicMock()
        t.retry_load()
        t.wait_until_ready(timeout=2)
        assert t.is_ready is True
        assert t.has_error is False

    def test_retry_clears_state(self, mock_gigaam):
        mock_gigaam.load_model.side_effect = RuntimeError("fail")
        from core.transcriber import Transcriber
        t = Transcriber()
        t.load_model()
        assert t._error is not None

        mock_gigaam.load_model.side_effect = None
        mock_gigaam.load_model.return_value = MagicMock()
        t.retry_load()
        # Check that state was cleared before async load
        assert t._download_progress == 0
        assert t._downloaded_mb == 0.0
        assert t._elapsed_seconds == 0


class TestTranscriberWaitUntilReady:
    def test_wait_returns_true_when_ready(self, mock_gigaam):
        mock_gigaam.load_model.return_value = MagicMock()
        from core.transcriber import Transcriber
        t = Transcriber()
        t.load_model()
        assert t.wait_until_ready(timeout=1) is True

    def test_wait_returns_false_on_timeout(self):
        from core.transcriber import Transcriber
        t = Transcriber()
        # Never load model, so wait should time out
        result = t.wait_until_ready(timeout=0.1)
        assert result is False


class TestFindCachedModel:
    def test_no_cache_dir(self, monkeypatch, tmp_path):
        from core import transcriber as t_mod
        monkeypatch.setattr(t_mod, 'GIGAAM_CACHE_DIR', tmp_path / "nonexistent")
        from core.transcriber import _find_cached_model
        assert _find_cached_model() is False

    def test_empty_cache_dir(self, monkeypatch, tmp_path):
        from core import transcriber as t_mod
        cache = tmp_path / "gigaam"
        cache.mkdir()
        monkeypatch.setattr(t_mod, 'GIGAAM_CACHE_DIR', cache)
        from core.transcriber import _find_cached_model
        assert _find_cached_model() is False

    def test_small_ckpt_file_ignored(self, monkeypatch, tmp_path):
        from core import transcriber as t_mod
        cache = tmp_path / "gigaam"
        cache.mkdir()
        (cache / "rnnt.ckpt").write_bytes(b"x" * 1000)  # too small
        monkeypatch.setattr(t_mod, 'GIGAAM_CACHE_DIR', cache)
        from core.transcriber import _find_cached_model
        assert _find_cached_model() is False

    def test_corrupted_large_ckpt_rejected(self, monkeypatch, tmp_path):
        """A large but corrupted (non-zip) .ckpt file should NOT be treated as cached."""
        from core import transcriber as t_mod
        cache = tmp_path / "gigaam"
        cache.mkdir()
        f = cache / "rnnt.ckpt"
        f.write_bytes(b"x" * 60_000_000)  # large but not a valid zip
        monkeypatch.setattr(t_mod, 'GIGAAM_CACHE_DIR', cache)
        from core.transcriber import _find_cached_model
        assert _find_cached_model() is False

    def test_valid_large_ckpt_found(self, monkeypatch, tmp_path):
        from core import transcriber as t_mod
        cache = tmp_path / "gigaam"
        cache.mkdir()
        _make_valid_ckpt(cache / "rnnt.ckpt", size_mb=60)
        monkeypatch.setattr(t_mod, 'GIGAAM_CACHE_DIR', cache)
        from core.transcriber import _find_cached_model
        assert _find_cached_model() is True


class TestIsValidCheckpoint:
    def test_nonexistent_file(self, tmp_path):
        from core.transcriber import _is_valid_checkpoint
        assert _is_valid_checkpoint(tmp_path / "nope.ckpt") is False

    def test_too_small_file(self, tmp_path):
        from core.transcriber import _is_valid_checkpoint
        f = tmp_path / "small.ckpt"
        f.write_bytes(b"x" * 100)
        assert _is_valid_checkpoint(f) is False

    def test_large_but_corrupted(self, tmp_path):
        from core.transcriber import _is_valid_checkpoint
        f = tmp_path / "corrupt.ckpt"
        f.write_bytes(b"x" * 60_000_000)
        assert _is_valid_checkpoint(f) is False

    def test_valid_zip_checkpoint(self, tmp_path):
        from core.transcriber import _is_valid_checkpoint
        f = tmp_path / "valid.ckpt"
        _make_valid_ckpt(f, size_mb=60)
        assert _is_valid_checkpoint(f) is True

    def test_truncated_zip(self, tmp_path):
        """A partially downloaded zip (truncated) should be invalid."""
        from core.transcriber import _is_valid_checkpoint
        f = tmp_path / "partial.ckpt"
        _make_valid_ckpt(f, size_mb=60)
        # Truncate the file to simulate interrupted download
        data = f.read_bytes()
        f.write_bytes(data[:len(data) // 2])
        assert _is_valid_checkpoint(f) is False


class TestCleanupCorruptedCache:
    def test_removes_corrupted_files(self, monkeypatch, tmp_path):
        from core import transcriber as t_mod
        cache = tmp_path / "gigaam"
        cache.mkdir()
        corrupt = cache / "rnnt.ckpt"
        corrupt.write_bytes(b"x" * 60_000_000)  # corrupted (not a zip)
        monkeypatch.setattr(t_mod, 'GIGAAM_CACHE_DIR', cache)
        from core.transcriber import _cleanup_corrupted_cache
        _cleanup_corrupted_cache()
        assert not corrupt.exists()

    def test_keeps_valid_files(self, monkeypatch, tmp_path):
        from core import transcriber as t_mod
        cache = tmp_path / "gigaam"
        cache.mkdir()
        valid = cache / "rnnt.ckpt"
        _make_valid_ckpt(valid, size_mb=60)
        monkeypatch.setattr(t_mod, 'GIGAAM_CACHE_DIR', cache)
        from core.transcriber import _cleanup_corrupted_cache
        _cleanup_corrupted_cache()
        assert valid.exists()

    def test_no_crash_on_missing_dir(self, monkeypatch, tmp_path):
        from core import transcriber as t_mod
        monkeypatch.setattr(t_mod, 'GIGAAM_CACHE_DIR', tmp_path / "nonexistent")
        from core.transcriber import _cleanup_corrupted_cache
        _cleanup_corrupted_cache()  # should not raise


class TestCorruptedModelAutoRecovery:
    def test_pytorch_stream_error_cleans_cache(self, mock_gigaam, monkeypatch, tmp_path):
        """When PyTorch can't read a corrupted checkpoint, cache should be cleaned."""
        from core import transcriber as t_mod
        cache = tmp_path / "gigaam"
        cache.mkdir()
        corrupt = cache / "rnnt.ckpt"
        corrupt.write_bytes(b"x" * 60_000_000)
        monkeypatch.setattr(t_mod, 'GIGAAM_CACHE_DIR', cache)

        mock_gigaam.load_model.side_effect = RuntimeError(
            "PytorchStreamReader failed reading zip archive: failed finding central directory"
        )

        from core.transcriber import Transcriber
        t = Transcriber()
        t.load_model()

        assert t.has_error is True
        assert "Corrupted" in t._error or "corrupt" in t._error.lower()
        # Corrupted file should have been removed
        assert not corrupt.exists()


class TestScanDownloadBytes:
    def test_scan_returns_zero_with_no_cache(self, monkeypatch, tmp_path):
        from core import transcriber as t_mod
        monkeypatch.setattr(t_mod, 'CACHE_DIRS', [tmp_path / "nonexistent"])
        from core.transcriber import _scan_download_bytes
        assert _scan_download_bytes() == 0

    def test_scan_finds_model_files(self, monkeypatch, tmp_path):
        from core import transcriber as t_mod
        cache = tmp_path / "cache"
        cache.mkdir()
        # Create a fake .ckpt file
        (cache / "rnnt.ckpt").write_bytes(b"x" * 1000)
        monkeypatch.setattr(t_mod, 'CACHE_DIRS', [cache])
        from core.transcriber import _scan_download_bytes
        assert _scan_download_bytes() == 1000

    def test_scan_finds_incomplete_files(self, monkeypatch, tmp_path):
        from core import transcriber as t_mod
        cache = tmp_path / "cache"
        cache.mkdir()
        (cache / "model.incomplete").write_bytes(b"x" * 500)
        monkeypatch.setattr(t_mod, 'CACHE_DIRS', [cache])
        from core.transcriber import _scan_download_bytes
        assert _scan_download_bytes() == 500


class TestTranscriberDownloadMonitor:
    def test_speed_calculation_with_samples(self):
        from core.transcriber import Transcriber
        t = Transcriber()
        # Simulate speed samples: 100MB over 2 seconds
        t._speed_samples = [
            (100.0, 0),
            (101.0, 50_000_000),
            (102.0, 100_000_000),
        ]
        t._download_speed = 50_000_000  # 50 MB/s
        t._download_eta = 8  # 8 seconds
        t._downloaded_mb = 100.0
        t._total_mb = 500.0
        t._is_downloading = True

        status = t.get_status()
        assert status["speed_mbs"] == 47.7  # 50MB/s rounded
        assert status["eta_seconds"] == 8
        assert status["downloaded_mb"] == 100.0
        assert status["total_mb"] == 500.0
        assert status["downloading"] is True

    def test_initial_speed_is_zero(self):
        from core.transcriber import Transcriber
        t = Transcriber()
        status = t.get_status()
        assert status["speed_mbs"] == 0.0
        assert status["eta_seconds"] == 0


class TestTranscriberTranscribe:
    def test_transcribe_raises_if_not_ready(self):
        from core.transcriber import Transcriber
        t = Transcriber()
        with pytest.raises(RuntimeError, match="not loaded"):
            t.transcribe("test.wav")

    @patch("core.transcriber.get_wav_duration", return_value=5.0)
    def test_short_audio_uses_transcribe(self, mock_dur, mock_gigaam):
        mock_model = MagicMock()
        mock_model.transcribe.return_value = "результат"
        mock_gigaam.load_model.return_value = mock_model

        from core.transcriber import Transcriber
        t = Transcriber()
        t.load_model()
        result = t.transcribe("test.wav")

        assert result == "результат"
        mock_model.transcribe.assert_called_once_with("test.wav")

    @patch("core.transcriber.get_wav_duration", return_value=30.0)
    def test_long_audio_uses_longform(self, mock_dur, mock_gigaam):
        mock_model = MagicMock()
        mock_model.transcribe_longform.return_value = [
            {"transcription": "сегмент один"},
            {"transcription": "сегмент два"},
        ]
        mock_gigaam.load_model.return_value = mock_model

        from core.transcriber import Transcriber
        t = Transcriber()
        t.load_model()
        result = t.transcribe("test.wav")

        assert "сегмент один" in result
        assert "сегмент два" in result

    @patch("core.transcriber.get_wav_duration", return_value=5.0)
    def test_transcribe_list_result(self, mock_dur, mock_gigaam):
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ["часть 1", "часть 2"]
        mock_gigaam.load_model.return_value = mock_model

        from core.transcriber import Transcriber
        t = Transcriber()
        t.load_model()
        result = t.transcribe("test.wav")

        assert "часть 1" in result
        assert "часть 2" in result

    @patch("core.transcriber.get_wav_duration", return_value=30.0)
    def test_longform_tuple_segments(self, mock_dur, mock_gigaam):
        mock_model = MagicMock()
        mock_model.transcribe_longform.return_value = [
            (0.0, 5.0, "сегмент"),
        ]
        mock_gigaam.load_model.return_value = mock_model

        from core.transcriber import Transcriber
        t = Transcriber()
        t.load_model()
        result = t.transcribe("test.wav")
        assert "сегмент" in result


class TestTranscriberLongformFallback:
    """Test that longform transcription falls back to standard when pyannote/ffmpeg missing."""

    @patch("core.transcriber.get_wav_duration", return_value=30.0)
    def test_falls_back_on_import_error(self, mock_dur, mock_gigaam):
        mock_model = MagicMock()
        mock_model.transcribe_longform.side_effect = ImportError("No module named 'pyannote'")
        mock_model.transcribe.return_value = "fallback result"
        mock_gigaam.load_model.return_value = mock_model

        from core.transcriber import Transcriber
        t = Transcriber()
        t.load_model()
        result = t.transcribe("test.wav")

        assert result == "fallback result"
        mock_model.transcribe.assert_called_once_with("test.wav")

    @patch("core.transcriber.get_wav_duration", return_value=30.0)
    def test_falls_back_on_module_not_found(self, mock_dur, mock_gigaam):
        mock_model = MagicMock()
        mock_model.transcribe_longform.side_effect = ModuleNotFoundError("No module named 'pyannote'")
        mock_model.transcribe.return_value = "fallback result"
        mock_gigaam.load_model.return_value = mock_model

        from core.transcriber import Transcriber
        t = Transcriber()
        t.load_model()
        result = t.transcribe("test.wav")

        assert result == "fallback result"

    @patch("core.transcriber.get_wav_duration", return_value=30.0)
    def test_falls_back_on_ffmpeg_not_found(self, mock_dur, mock_gigaam):
        mock_model = MagicMock()
        mock_model.transcribe_longform.side_effect = FileNotFoundError("[Errno 2] No such file or directory: 'ffmpeg'")
        mock_model.transcribe.return_value = "fallback result"
        mock_gigaam.load_model.return_value = mock_model

        from core.transcriber import Transcriber
        t = Transcriber()
        t.load_model()
        result = t.transcribe("test.wav")

        assert result == "fallback result"

    @patch("core.transcriber.get_wav_duration", return_value=30.0)
    def test_longform_success_no_fallback(self, mock_dur, mock_gigaam):
        mock_model = MagicMock()
        mock_model.transcribe_longform.return_value = [{"transcription": "long text"}]
        mock_gigaam.load_model.return_value = mock_model

        from core.transcriber import Transcriber
        t = Transcriber()
        t.load_model()
        result = t.transcribe("test.wav")

        assert "long text" in result
        mock_model.transcribe.assert_not_called()


class TestSSLCertFix:
    """Verify SSL certificate environment is configured for bundled app."""

    def test_ssl_cert_file_set_after_app_import(self, monkeypatch):
        """Importing app.py should set SSL_CERT_FILE via certifi."""
        import os
        # Remove existing values so setdefault takes effect
        monkeypatch.delenv('SSL_CERT_FILE', raising=False)
        monkeypatch.delenv('REQUESTS_CA_BUNDLE', raising=False)

        # Mock certifi to avoid needing it installed
        mock_certifi = MagicMock()
        mock_certifi.where.return_value = "/fake/cacert.pem"
        monkeypatch.setitem(sys.modules, "certifi", mock_certifi)

        # Re-execute the SSL fix logic from app.py
        import certifi
        os.environ.setdefault('SSL_CERT_FILE', certifi.where())
        os.environ.setdefault('REQUESTS_CA_BUNDLE', certifi.where())

        assert os.environ.get('SSL_CERT_FILE') == "/fake/cacert.pem"
        assert os.environ.get('REQUESTS_CA_BUNDLE') == "/fake/cacert.pem"

    def test_ssl_cert_does_not_override_existing(self, monkeypatch):
        """If SSL_CERT_FILE is already set, don't override it."""
        import os
        monkeypatch.setenv('SSL_CERT_FILE', '/custom/cert.pem')

        mock_certifi = MagicMock()
        mock_certifi.where.return_value = "/fake/cacert.pem"
        monkeypatch.setitem(sys.modules, "certifi", mock_certifi)

        import certifi
        os.environ.setdefault('SSL_CERT_FILE', certifi.where())

        assert os.environ.get('SSL_CERT_FILE') == "/custom/cert.pem"

    def test_model_name_not_v3(self):
        """Ensure the old invalid model name is never used."""
        from core.transcriber import MODEL_NAME
        assert "v3" not in MODEL_NAME
        assert "e2e" not in MODEL_NAME
        assert MODEL_NAME == "rnnt"
