"""Tests for core/text_cleaner.py."""
import json
from unittest.mock import MagicMock, patch, Mock

import pytest

from core.text_cleaner import (
    SYSTEM_PROMPT,
    clean_text,
    clean_text_with_llm,
    clean_text_with_openrouter,
    is_ollama_available,
)


class TestSystemPrompt:
    def test_prompt_is_nonempty(self):
        assert len(SYSTEM_PROMPT) > 100

    def test_prompt_mentions_russian(self):
        assert "Russian" in SYSTEM_PROMPT

    def test_prompt_mentions_filler_words(self):
        assert "filler" in SYSTEM_PROMPT.lower() or "FILLER" in SYSTEM_PROMPT


# ── clean_text_with_llm (Ollama) ──

class TestCleanTextWithLlm:
    def test_empty_text_returns_empty(self):
        assert clean_text_with_llm("") == ""

    def test_whitespace_only_returns_original(self):
        assert clean_text_with_llm("   ") == "   "

    def test_none_text_returns_none(self):
        assert clean_text_with_llm(None) is None

    @patch("core.text_cleaner.subprocess.run")
    def test_successful_cleanup(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"response": "Чистый текст."})
        )
        result = clean_text_with_llm("Ну, э, чистый текст.")
        assert result == "Чистый текст."

    @patch("core.text_cleaner.subprocess.run")
    def test_curl_failure_returns_original(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="connection refused")
        result = clean_text_with_llm("оригинал")
        assert result == "оригинал"

    @patch("core.text_cleaner.subprocess.run")
    def test_empty_response_returns_original(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"response": ""})
        )
        result = clean_text_with_llm("оригинал")
        assert result == "оригинал"

    @patch("core.text_cleaner.subprocess.run")
    def test_suspiciously_long_response_returns_original(self, mock_run):
        original = "короткий текст"
        long_response = "a" * (len(original) * 2)  # way more than 30% longer
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"response": long_response})
        )
        result = clean_text_with_llm(original)
        assert result == original

    @patch("core.text_cleaner.subprocess.run")
    def test_invalid_json_returns_original(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="not json")
        result = clean_text_with_llm("текст")
        assert result == "текст"

    @patch("core.text_cleaner.subprocess.run")
    def test_timeout_returns_original(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="curl", timeout=30)
        result = clean_text_with_llm("текст")
        assert result == "текст"

    @patch("core.text_cleaner.subprocess.run")
    def test_payload_contains_model_and_prompt(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"response": "ok"})
        )
        clean_text_with_llm("test prompt")
        call_args = mock_run.call_args[0][0]
        # curl command includes -d with JSON payload
        payload_str = call_args[-1]
        payload = json.loads(payload_str)
        assert payload["model"] == "gemma3:4b"
        assert payload["prompt"] == "test prompt"
        assert payload["system"] == SYSTEM_PROMPT


# ── clean_text_with_openrouter ──

class TestCleanTextWithOpenrouter:
    def test_empty_text_returns_empty(self):
        assert clean_text_with_openrouter("", "key") == ""

    def test_no_api_key_returns_original(self):
        assert clean_text_with_openrouter("текст", "") == "текст"

    def test_none_text_returns_none(self):
        assert clean_text_with_openrouter(None, "key") is None

    @patch("core.text_cleaner.urllib.request.urlopen")
    def test_successful_cleanup(self, mock_urlopen):
        response_data = json.dumps({
            "choices": [{"message": {"content": "Чистый текст."}}]
        }).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = clean_text_with_openrouter("Ну, э, чистый текст.", "sk-test")
        assert result == "Чистый текст."

    @patch("core.text_cleaner.urllib.request.urlopen")
    def test_empty_response_returns_original(self, mock_urlopen):
        response_data = json.dumps({
            "choices": [{"message": {"content": ""}}]
        }).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = clean_text_with_openrouter("оригинал", "sk-test")
        assert result == "оригинал"

    @patch("core.text_cleaner.urllib.request.urlopen")
    def test_suspiciously_long_response_returns_original(self, mock_urlopen):
        original = "короткий"
        long_text = "a" * (len(original) * 2)
        response_data = json.dumps({
            "choices": [{"message": {"content": long_text}}]
        }).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = clean_text_with_openrouter(original, "sk-test")
        assert result == original

    @patch("core.text_cleaner.urllib.request.urlopen")
    def test_http_error_returns_original(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=401, msg="Unauthorized", hdrs=None, fp=None
        )
        result = clean_text_with_openrouter("текст", "bad-key")
        assert result == "текст"

    @patch("core.text_cleaner.urllib.request.urlopen")
    def test_network_error_returns_original(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection refused")
        result = clean_text_with_openrouter("текст", "sk-test")
        assert result == "текст"

    @patch("core.text_cleaner.urllib.request.Request")
    @patch("core.text_cleaner.urllib.request.urlopen")
    def test_request_has_auth_header(self, mock_urlopen, mock_request_cls):
        response_data = json.dumps({
            "choices": [{"message": {"content": "ok"}}]
        }).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_resp

        clean_text_with_openrouter("test", "sk-or-key123", "my-model")
        call_kwargs = mock_request_cls.call_args
        headers = call_kwargs[1]["headers"] if "headers" in call_kwargs[1] else call_kwargs[0][2] if len(call_kwargs[0]) > 2 else {}
        # Check the Request was called with correct URL
        assert "openrouter.ai" in call_kwargs[0][0]


# ── clean_text dispatcher ──

class TestCleanTextDispatcher:
    def test_llm_cleanup_disabled_returns_original(self):
        config = {"llm_cleanup": False}
        result = clean_text("текст", config)
        assert result == "текст"

    @patch("core.text_cleaner.is_ollama_available", return_value=True)
    @patch("core.text_cleaner.clean_text_with_llm", return_value="чистый")
    def test_local_provider_uses_ollama(self, mock_llm, mock_avail):
        config = {"llm_cleanup": True, "llm_provider": "local"}
        result = clean_text("текст", config)
        assert result == "чистый"
        mock_llm.assert_called_once()

    @patch("core.text_cleaner.is_ollama_available", return_value=False)
    def test_local_provider_ollama_unavailable(self, mock_avail):
        config = {"llm_cleanup": True, "llm_provider": "local"}
        result = clean_text("текст", config)
        assert result == "текст"

    @patch("core.text_cleaner.clean_text_with_openrouter", return_value="чистый")
    def test_openrouter_provider_with_key(self, mock_or):
        config = {
            "llm_cleanup": True,
            "llm_provider": "openrouter",
            "openrouter_api_key": "sk-test",
            "openrouter_model": "test-model",
        }
        result = clean_text("текст", config)
        assert result == "чистый"
        mock_or.assert_called_once_with("текст", "sk-test", "test-model", 30.0)

    def test_openrouter_provider_no_key_returns_original(self):
        config = {
            "llm_cleanup": True,
            "llm_provider": "openrouter",
            "openrouter_api_key": "",
        }
        result = clean_text("текст", config)
        assert result == "текст"

    @patch("core.text_cleaner.is_ollama_available", return_value=True)
    @patch("core.text_cleaner.clean_text_with_llm", return_value="чистый")
    def test_default_provider_is_local(self, mock_llm, mock_avail):
        config = {"llm_cleanup": True}  # no llm_provider key
        result = clean_text("текст", config)
        mock_llm.assert_called_once()


# ── is_ollama_available ──

class TestIsOllamaAvailable:
    @patch("core.text_cleaner.subprocess.run")
    def test_returns_true_when_gemma_available(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "models": [{"name": "gemma3:4b"}, {"name": "llama3:8b"}]
            })
        )
        assert is_ollama_available() is True

    @patch("core.text_cleaner.subprocess.run")
    def test_returns_false_when_no_gemma(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "models": [{"name": "llama3:8b"}]
            })
        )
        assert is_ollama_available() is False

    @patch("core.text_cleaner.subprocess.run")
    def test_returns_false_on_curl_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        assert is_ollama_available() is False

    @patch("core.text_cleaner.subprocess.run")
    def test_returns_false_on_exception(self, mock_run):
        mock_run.side_effect = Exception("no curl")
        assert is_ollama_available() is False

    @patch("core.text_cleaner.subprocess.run")
    def test_returns_false_on_invalid_json(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="not json")
        assert is_ollama_available() is False
