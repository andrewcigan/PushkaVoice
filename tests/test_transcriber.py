"""Tests for core/transcriber.py."""
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest


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
        assert t._speed_samples == []


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

    def test_large_ckpt_file_found(self, monkeypatch, tmp_path):
        from core import transcriber as t_mod
        cache = tmp_path / "gigaam"
        cache.mkdir()
        # Create file > 50MB (we'll fake it with a sparse check)
        f = cache / "rnnt.ckpt"
        f.write_bytes(b"x" * 60_000_000)
        monkeypatch.setattr(t_mod, 'GIGAAM_CACHE_DIR', cache)
        from core.transcriber import _find_cached_model
        assert _find_cached_model() is True


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
