"""Tests for ui/window.py — Api class (integration tests)."""
import os
import sys
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def mock_system_deps(monkeypatch):
    """Mock system dependencies that are unavailable on Linux."""
    mock_sd = MagicMock()
    mock_sd.query_devices.return_value = []
    monkeypatch.setitem(sys.modules, "sounddevice", mock_sd)
    return mock_sd


@pytest.fixture
def api(config, mock_transcriber):
    from ui.window import Api
    a = Api(config, mock_transcriber)
    a.state = "idle"
    return a


@pytest.fixture
def dictation_dir(config, tmp_path):
    """Set up dictations folder."""
    d = tmp_path / "dictations"
    d.mkdir()
    config.set("dictations_folder", str(d))
    return d


class TestApiInit:
    def test_initial_state_is_loading(self, config, mock_transcriber):
        from ui.window import Api
        a = Api(config, mock_transcriber)
        assert a._state == "loading"

    def test_statusbar_is_none(self, config, mock_transcriber):
        from ui.window import Api
        a = Api(config, mock_transcriber)
        assert a._statusbar is None


class TestApiState:
    def test_set_state(self, api):
        api.state = "recording"
        assert api.state == "recording"

    def test_set_state_notifies_statusbar(self, api):
        mock_sb = MagicMock()
        api.set_statusbar(mock_sb)
        api.state = "transcribing"
        mock_sb.set_state.assert_called_with("transcribing")

    def test_get_state_transitions_from_loading(self, config, mock_transcriber):
        from ui.window import Api
        mock_transcriber.is_ready = True
        a = Api(config, mock_transcriber)
        assert a._state == "loading"
        result = a.get_state()
        assert result == "idle"

    def test_get_state_stays_loading_if_not_ready(self, config):
        from ui.window import Api
        t = MagicMock()
        t.is_ready = False
        t.is_downloading = False
        a = Api(config, t)
        assert a.get_state() == "loading"


class TestApiGetConfig:
    def test_returns_all_keys(self, api):
        cfg = api.get_config()
        assert "hotkey" in cfg
        assert "microphone_device_id" in cfg
        assert "auto_paste" in cfg
        assert "sample_rate" in cfg
        assert "llm_provider" in cfg
        assert "openrouter_api_key" in cfg
        assert "openrouter_model" in cfg

    def test_returns_correct_values(self, api):
        cfg = api.get_config()
        assert cfg["hotkey"] == "<cmd>+<shift>+d"
        assert cfg["auto_paste"] is True
        assert cfg["llm_provider"] == "local"

    def test_returns_all_keys_including_setup(self, api):
        # Ensure is_setup_complete is available as a method
        assert hasattr(api, 'is_setup_complete')
        assert hasattr(api, 'complete_setup')


class TestApiSetConfig:
    def test_set_config_persists(self, api):
        api.set_config("hotkey", "<f5>")
        assert api.config.hotkey == "<f5>"

    def test_set_llm_provider(self, api):
        api.set_config("llm_provider", "openrouter")
        assert api.config.get("llm_provider") == "openrouter"

    def test_set_openrouter_key(self, api):
        api.set_config("openrouter_api_key", "sk-test")
        assert api.config.get("openrouter_api_key") == "sk-test"


class TestApiSetup:
    def test_is_setup_complete_default_false(self, api):
        assert api.is_setup_complete() is False

    def test_is_setup_complete_after_setup(self, api):
        api.config.set("setup_complete", True)
        assert api.is_setup_complete() is True

    def test_complete_setup_local(self, api):
        api.transcriber.is_ready = False
        api.transcriber.is_loading = False
        result = api.complete_setup("local")
        assert result == {"ok": True}
        assert api.config.get("llm_provider") == "local"
        assert api.config.get("setup_complete") is True
        api.transcriber.load_model_async.assert_called_once()

    def test_complete_setup_openrouter(self, api):
        api.transcriber.is_ready = False
        api.transcriber.is_loading = False
        result = api.complete_setup("openrouter")
        assert result == {"ok": True}
        assert api.config.get("llm_provider") == "openrouter"
        assert api.config.get("setup_complete") is True

    def test_complete_setup_does_not_reload_if_ready(self, api):
        api.transcriber.is_ready = True
        api.complete_setup("local")
        api.transcriber.load_model_async.assert_not_called()

    def test_complete_setup_does_not_reload_if_loading(self, api):
        api.transcriber.is_loading = True
        api.complete_setup("local")
        api.transcriber.load_model_async.assert_not_called()


class TestApiWaitForModel:
    def test_returns_true_when_ready(self, api):
        api.mock_transcriber = api.transcriber
        api.transcriber.is_ready = True
        assert api.wait_for_model() is True
        assert api.state == "idle"

    def test_returns_false_when_not_ready(self, config):
        from ui.window import Api
        t = MagicMock()
        t.is_ready = False
        a = Api(config, t)
        assert a.wait_for_model() is False


class TestApiStartRecording:
    @patch("ui.window.AudioRecorder")
    def test_start_recording_from_idle(self, mock_rec_cls, api):
        mock_rec = MagicMock()
        mock_rec_cls.return_value = mock_rec

        result = api.start_recording()
        assert result == {"ok": True}
        assert api.state == "recording"
        mock_rec.start.assert_called_once()

    def test_start_recording_when_not_idle(self, api):
        api.state = "transcribing"
        result = api.start_recording()
        assert "error" in result

    @patch("ui.window.AudioRecorder")
    def test_start_recording_from_error(self, mock_rec_cls, api):
        api.state = "error"
        mock_rec_cls.return_value = MagicMock()
        result = api.start_recording()
        assert result == {"ok": True}


class TestApiStopRecording:
    def test_stop_when_not_recording(self, api):
        api.state = "idle"
        result = api.stop_recording()
        assert "error" in result

    @patch("ui.window.copy_and_paste")
    @patch("ui.window.clean_text", return_value="чистый текст")
    @patch("ui.window.AudioRecorder")
    def test_stop_recording_full_flow(self, mock_rec_cls, mock_clean, mock_paste, api, dictation_dir):
        # Setup: start recording
        mock_rec = MagicMock()
        wav_path = str(dictation_dir / "test.wav")
        # Create actual wav file
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(np.zeros(1600, dtype=np.int16).tobytes())
        mock_rec.stop.return_value = wav_path
        mock_rec_cls.return_value = mock_rec

        api.start_recording()
        result = api.stop_recording()

        assert "text" in result
        assert api.state == "idle"

    @patch("ui.window.AudioRecorder")
    def test_stop_recording_no_audio(self, mock_rec_cls, api, dictation_dir):
        mock_rec = MagicMock()
        mock_rec.stop.return_value = ""
        mock_rec_cls.return_value = mock_rec

        api.start_recording()
        result = api.stop_recording()

        assert "error" in result
        assert api.state == "error"


class TestApiTranscribeFile:
    @patch("ui.window.copy_to_clipboard")
    @patch("ui.window.clean_text", return_value="чистый текст")
    def test_successful_transcription(self, mock_clean, mock_copy, api, dictation_dir):
        wav_path = str(dictation_dir / "test.wav")
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(np.zeros(1600, dtype=np.int16).tobytes())

        api.config.set("auto_paste", False)
        result = api._transcribe_file(wav_path)

        assert result["text"] == "чистый текст"
        assert api.state == "idle"
        # Check text files were saved
        assert os.path.exists(wav_path.replace(".wav", ".txt"))
        assert os.path.exists(wav_path.replace(".wav", ".raw.txt"))

    @patch("ui.window.clean_text", return_value="")
    def test_empty_transcription(self, mock_clean, api, dictation_dir):
        api.transcriber.transcribe.return_value = "   "
        wav_path = str(dictation_dir / "test.wav")
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(np.zeros(1600, dtype=np.int16).tobytes())

        result = api._transcribe_file(wav_path)
        assert "error" in result
        assert "No speech detected" in result["error"]

    def test_transcription_exception(self, api, dictation_dir):
        api.transcriber.transcribe.side_effect = RuntimeError("model error")
        wav_path = str(dictation_dir / "test.wav")
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00" * 100)

        result = api._transcribe_file(wav_path)
        assert "error" in result
        assert api.state == "error"

    @patch("ui.window.copy_and_paste")
    @patch("ui.window.clean_text", return_value="текст")
    def test_auto_paste_on(self, mock_clean, mock_paste, api, dictation_dir):
        api.config.set("auto_paste", True)
        wav_path = str(dictation_dir / "test.wav")
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(np.zeros(1600, dtype=np.int16).tobytes())

        api._transcribe_file(wav_path)
        mock_paste.assert_called_once_with("текст")

    @patch("ui.window.copy_to_clipboard")
    @patch("ui.window.clean_text", return_value="текст")
    def test_auto_paste_off(self, mock_clean, mock_copy, api, dictation_dir):
        api.config.set("auto_paste", False)
        wav_path = str(dictation_dir / "test.wav")
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(np.zeros(1600, dtype=np.int16).tobytes())

        api._transcribe_file(wav_path)
        mock_copy.assert_called_once_with("текст")


class TestApiRetryTranscription:
    def test_retry_nonexistent_file(self, api):
        result = api.retry_transcription("/nonexistent/file.wav")
        assert "error" in result

    @patch("ui.window.copy_to_clipboard")
    @patch("ui.window.clean_text", return_value="ретрай текст")
    def test_retry_success(self, mock_clean, mock_copy, api, dictation_dir):
        api.config.set("auto_paste", False)
        wav_path = str(dictation_dir / "test.wav")
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(np.zeros(1600, dtype=np.int16).tobytes())

        # Create error file that should be removed on success
        err_path = wav_path.replace(".wav", ".error.txt")
        with open(err_path, "w") as f:
            f.write("previous error")

        result = api.retry_transcription(wav_path)
        assert result["text"] == "ретрай текст"
        assert not os.path.exists(err_path)


class TestApiGetHistory:
    def test_empty_history(self, api, dictation_dir):
        history = api.get_history()
        assert history == []

    def test_history_with_transcribed_file(self, api, dictation_dir):
        wav_path = dictation_dir / "2024-01-15_14-30-00.wav"
        txt_path = dictation_dir / "2024-01-15_14-30-00.txt"

        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00" * 100)

        txt_path.write_text("Привет мир", encoding="utf-8")

        history = api.get_history()
        assert len(history) == 1
        assert history[0]["status"] == "ok"
        assert history[0]["text"] == "Привет мир"
        assert history[0]["time"] == "14:30"

    def test_history_with_error_file(self, api, dictation_dir):
        wav_path = dictation_dir / "2024-01-15_14-30-00.wav"
        err_path = dictation_dir / "2024-01-15_14-30-00.error.txt"

        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00" * 100)

        err_path.write_text("No speech detected", encoding="utf-8")

        history = api.get_history()
        assert len(history) == 1
        assert history[0]["status"] == "error"

    def test_history_with_pending_file(self, api, dictation_dir):
        wav_path = dictation_dir / "2024-01-15_14-30-00.wav"
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00" * 100)

        history = api.get_history()
        assert len(history) == 1
        assert history[0]["status"] == "pending"

    def test_history_limits_to_30(self, api, dictation_dir):
        for i in range(35):
            wav_path = dictation_dir / f"2024-01-15_14-{i:02d}-00.wav"
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b"\x00" * 100)

        history = api.get_history()
        assert len(history) == 30


class TestApiCopyText:
    @patch("ui.window.copy_to_clipboard")
    def test_copy_text(self, mock_copy, api):
        result = api.copy_text("тест")
        assert result == {"ok": True}
        mock_copy.assert_called_once_with("тест")


class TestApiOpenFolder:
    @patch("ui.window.subprocess.run")
    def test_opens_folder(self, mock_run, api):
        result = api.open_dictations_folder()
        assert result == {"ok": True}
        mock_run.assert_called_once()


class TestApiLogs:
    def test_get_log_path_returns_string(self, api):
        path = api.get_log_path()
        assert isinstance(path, str)
        assert "dictation.log" in path

    def test_get_logs_no_file(self, api, tmp_path, monkeypatch):
        # Point to nonexistent log
        monkeypatch.setattr(api, 'get_log_path', lambda: str(tmp_path / "nope.log"))
        result = api.get_logs()
        assert result["lines"] == []

    def test_get_logs_with_file(self, api, tmp_path, monkeypatch):
        log_file = tmp_path / "dictation.log"
        log_file.write_text("line1\nline2\nline3\n", encoding="utf-8")
        monkeypatch.setattr(api, 'get_log_path', lambda: str(log_file))
        result = api.get_logs()
        assert len(result["lines"]) == 3
        assert "line1" in result["lines"][0]

    def test_get_logs_max_lines(self, api, tmp_path, monkeypatch):
        log_file = tmp_path / "dictation.log"
        lines = [f"line {i}\n" for i in range(300)]
        log_file.write_text("".join(lines), encoding="utf-8")
        monkeypatch.setattr(api, 'get_log_path', lambda: str(log_file))
        result = api.get_logs(max_lines=50)
        assert len(result["lines"]) == 50
        # Should be the LAST 50 lines
        assert "line 250" in result["lines"][0]

    @patch("ui.window.subprocess.run")
    def test_open_log_file(self, mock_run, api):
        result = api.open_log_file()
        assert result["ok"] is True
        assert "path" in result


class TestApiGetDevices:
    @patch("ui.window.AudioRecorder.list_devices", return_value=[{"id": 0, "name": "Mic"}])
    def test_returns_devices(self, mock_devices, api):
        devices = api.get_devices()
        assert len(devices) == 1
        assert devices[0]["name"] == "Mic"
