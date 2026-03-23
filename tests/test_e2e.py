"""End-to-end tests: full record → transcribe → clean → clipboard flow."""
import os
import sys
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def mock_system_deps(monkeypatch):
    mock_sd = MagicMock()
    monkeypatch.setitem(sys.modules, "sounddevice", mock_sd)
    return mock_sd


@pytest.fixture
def setup_e2e(config, tmp_path):
    """Set up a full Api instance with mocked dependencies."""
    dictation_dir = tmp_path / "dictations"
    dictation_dir.mkdir()
    config.set("dictations_folder", str(dictation_dir))
    config.set("auto_paste", False)

    mock_transcriber = MagicMock()
    mock_transcriber.is_ready = True

    from ui.window import Api
    api = Api(config, mock_transcriber)
    api.state = "idle"

    return api, mock_transcriber, dictation_dir


class TestE2ELocalOllama:
    """Full flow with local Ollama provider."""

    @patch("ui.window.copy_to_clipboard")
    @patch("ui.window.clean_text")
    @patch("ui.window.AudioRecorder")
    def test_record_transcribe_clean_copy(self, mock_rec_cls, mock_clean, mock_copy, setup_e2e):
        api, mock_transcriber, dictation_dir = setup_e2e
        api.config.set("llm_provider", "local")
        api.config.set("llm_cleanup", True)

        # Setup recorder mock
        wav_path = str(dictation_dir / "test.wav")
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(np.zeros(8000, dtype=np.int16).tobytes())

        mock_rec = MagicMock()
        mock_rec.stop.return_value = wav_path
        mock_rec_cls.return_value = mock_rec

        # Setup transcriber
        mock_transcriber.transcribe.return_value = "ну вот, эм, привет мир"

        # Setup LLM cleanup
        mock_clean.return_value = "Привет мир."

        # Execute flow
        result = api.start_recording()
        assert result == {"ok": True}
        assert api.state == "recording"

        result = api.stop_recording()
        assert "text" in result
        assert result["text"] == "Привет мир."
        assert result["raw_text"] == "ну вот, эм, привет мир"
        assert api.state == "idle"

        # Verify files were saved
        assert os.path.exists(wav_path.replace(".wav", ".txt"))
        assert os.path.exists(wav_path.replace(".wav", ".raw.txt"))

        # Verify clipboard
        mock_copy.assert_called_once_with("Привет мир.")

        # Verify history
        history = api.get_history()
        assert len(history) == 1
        assert history[0]["status"] == "ok"


class TestE2EOpenRouter:
    """Full flow with OpenRouter provider."""

    @patch("ui.window.copy_to_clipboard")
    @patch("ui.window.clean_text")
    @patch("ui.window.AudioRecorder")
    def test_record_transcribe_openrouter_clean(self, mock_rec_cls, mock_clean, mock_copy, setup_e2e):
        api, mock_transcriber, dictation_dir = setup_e2e
        api.config.set("llm_provider", "openrouter")
        api.config.set("openrouter_api_key", "sk-or-test")
        api.config.set("openrouter_model", "google/gemma-3-4b-it:free")
        api.config.set("llm_cleanup", True)

        wav_path = str(dictation_dir / "test.wav")
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(np.zeros(8000, dtype=np.int16).tobytes())

        mock_rec = MagicMock()
        mock_rec.stop.return_value = wav_path
        mock_rec_cls.return_value = mock_rec

        mock_transcriber.transcribe.return_value = "эм, тестовый текст"
        mock_clean.return_value = "Тестовый текст."

        api.start_recording()
        result = api.stop_recording()

        assert result["text"] == "Тестовый текст."
        mock_copy.assert_called_once_with("Тестовый текст.")


class TestE2ENoLLM:
    """Full flow with LLM cleanup disabled."""

    @patch("ui.window.copy_to_clipboard")
    @patch("ui.window.clean_text")
    @patch("ui.window.AudioRecorder")
    def test_record_transcribe_no_cleanup(self, mock_rec_cls, mock_clean, mock_copy, setup_e2e):
        api, mock_transcriber, dictation_dir = setup_e2e
        api.config.set("llm_cleanup", False)

        wav_path = str(dictation_dir / "test.wav")
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(np.zeros(8000, dtype=np.int16).tobytes())

        mock_rec = MagicMock()
        mock_rec.stop.return_value = wav_path
        mock_rec_cls.return_value = mock_rec

        mock_transcriber.transcribe.return_value = "сырой текст"
        # clean_text should return original when cleanup is off
        mock_clean.return_value = "сырой текст"

        api.start_recording()
        result = api.stop_recording()

        assert result["text"] == "сырой текст"


class TestE2EErrorRecovery:
    """Test error handling and retry flows."""

    @patch("ui.window.AudioRecorder")
    def test_transcription_error_then_retry(self, mock_rec_cls, setup_e2e):
        api, mock_transcriber, dictation_dir = setup_e2e

        wav_path = str(dictation_dir / "test.wav")
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(np.zeros(8000, dtype=np.int16).tobytes())

        mock_rec = MagicMock()
        mock_rec.stop.return_value = wav_path
        mock_rec_cls.return_value = mock_rec

        # First attempt: error
        mock_transcriber.transcribe.side_effect = RuntimeError("GPU out of memory")

        api.start_recording()
        result = api.stop_recording()
        assert "error" in result
        assert api.state == "error"

        # Check error file exists
        err_path = wav_path.replace(".wav", ".error.txt")
        assert os.path.exists(err_path)

        # History shows error
        history = api.get_history()
        assert len(history) == 1
        assert history[0]["status"] == "error"

        # Retry: success
        mock_transcriber.transcribe.side_effect = None
        mock_transcriber.transcribe.return_value = "успешный текст"

        with patch("ui.window.clean_text", return_value="успешный текст"), \
             patch("ui.window.copy_to_clipboard"):
            result = api.retry_transcription(wav_path)

        assert result["text"] == "успешный текст"
        assert not os.path.exists(err_path)  # error file removed

    @patch("ui.window.AudioRecorder")
    def test_no_audio_captured(self, mock_rec_cls, setup_e2e):
        api, mock_transcriber, dictation_dir = setup_e2e

        mock_rec = MagicMock()
        mock_rec.stop.return_value = ""  # no audio
        mock_rec_cls.return_value = mock_rec

        api.start_recording()
        result = api.stop_recording()
        assert "error" in result
        assert "No audio captured" in result["error"]
        assert api.state == "error"


class TestE2EConfigPersistence:
    """Test that LLM settings persist across config reloads."""

    def test_openrouter_settings_persist(self, make_config):
        c1 = make_config()
        c1.set("llm_provider", "openrouter")
        c1.set("openrouter_api_key", "sk-or-persistent")
        c1.set("openrouter_model", "anthropic/claude-3-haiku")

        c2 = make_config()
        assert c2.get("llm_provider") == "openrouter"
        assert c2.get("openrouter_api_key") == "sk-or-persistent"
        assert c2.get("openrouter_model") == "anthropic/claude-3-haiku"


class TestE2ESetupFlow:
    """Test the initial setup flow."""

    def test_setup_not_complete_by_default(self, setup_e2e):
        api, _, _ = setup_e2e
        assert api.is_setup_complete() is False

    def test_complete_setup_with_local(self, setup_e2e):
        api, mock_transcriber, _ = setup_e2e
        mock_transcriber.is_ready = False
        mock_transcriber.is_loading = False
        result = api.complete_setup("local")
        assert result == {"ok": True}
        assert api.config.get("llm_provider") == "local"
        assert api.config.get("setup_complete") is True
        mock_transcriber.load_model_async.assert_called_once()

    def test_complete_setup_with_cloud(self, setup_e2e):
        api, mock_transcriber, _ = setup_e2e
        mock_transcriber.is_ready = False
        mock_transcriber.is_loading = False
        result = api.complete_setup("openrouter")
        assert result == {"ok": True}
        assert api.config.get("llm_provider") == "openrouter"
        assert api.config.get("setup_complete") is True
        mock_transcriber.load_model_async.assert_called_once()

    def test_setup_persists_across_instances(self, make_config):
        c1 = make_config()
        c1.set("setup_complete", True)
        c1.set("llm_provider", "openrouter")

        c2 = make_config()
        assert c2.get("setup_complete") is True
        assert c2.get("llm_provider") == "openrouter"


class TestE2EProviderSwitching:
    """Test switching between providers mid-session."""

    @patch("ui.window.copy_to_clipboard")
    @patch("ui.window.AudioRecorder")
    def test_switch_from_local_to_openrouter(self, mock_rec_cls, mock_copy, setup_e2e):
        api, mock_transcriber, dictation_dir = setup_e2e

        # Start with local
        api.config.set("llm_provider", "local")
        cfg = api.get_config()
        assert cfg["llm_provider"] == "local"

        # Switch to openrouter
        api.set_config("llm_provider", "openrouter")
        api.set_config("openrouter_api_key", "sk-or-new")
        cfg = api.get_config()
        assert cfg["llm_provider"] == "openrouter"
        assert cfg["openrouter_api_key"] == "sk-or-new"

        # Do a transcription with new provider
        wav_path = str(dictation_dir / "test.wav")
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(np.zeros(8000, dtype=np.int16).tobytes())

        mock_rec = MagicMock()
        mock_rec.stop.return_value = wav_path
        mock_rec_cls.return_value = mock_rec
        mock_transcriber.transcribe.return_value = "текст"

        with patch("ui.window.clean_text", return_value="текст") as mock_clean:
            api.start_recording()
            result = api.stop_recording()
            # Verify clean_text was called with the config that has openrouter
            mock_clean.assert_called_once()
            call_config = mock_clean.call_args[0][1]
            assert call_config.get("llm_provider") == "openrouter"
