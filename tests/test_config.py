"""Tests for utils/config.py."""
import json

import pytest


class TestConfigDefaults:
    def test_default_hotkey(self, config):
        assert config.hotkey == "<cmd>+<shift>+d"

    def test_default_microphone_device_id(self, config):
        assert config.microphone_device_id is None

    def test_default_auto_paste(self, config):
        assert config.auto_paste is True

    def test_default_sample_rate(self, config):
        assert config.sample_rate == 16000

    def test_default_llm_cleanup(self, config):
        assert config.get("llm_cleanup") is True

    def test_default_llm_provider(self, config):
        assert config.get("llm_provider") == "local"

    def test_default_openrouter_api_key(self, config):
        assert config.get("openrouter_api_key") == ""

    def test_default_openrouter_model(self, config):
        assert config.get("openrouter_model") == "google/gemma-3-4b-it:free"

    def test_default_setup_complete(self, config):
        assert config.get("setup_complete") is False


class TestConfigGetSet:
    def test_get_existing_key(self, config):
        assert config.get("hotkey") == "<cmd>+<shift>+d"

    def test_get_missing_key_returns_default(self, config):
        assert config.get("nonexistent", "fallback") == "fallback"

    def test_get_missing_key_returns_none(self, config):
        assert config.get("nonexistent") is None

    def test_set_and_get(self, config):
        config.set("hotkey", "<f5>")
        assert config.get("hotkey") == "<f5>"
        assert config.hotkey == "<f5>"

    def test_set_new_key(self, config):
        config.set("custom_key", 42)
        assert config.get("custom_key") == 42

    def test_set_llm_provider(self, config):
        config.set("llm_provider", "openrouter")
        assert config.get("llm_provider") == "openrouter"

    def test_set_openrouter_api_key(self, config):
        config.set("openrouter_api_key", "sk-or-test-key")
        assert config.get("openrouter_api_key") == "sk-or-test-key"


class TestConfigPersistence:
    def test_save_and_load(self, make_config, tmp_config_path):
        c1 = make_config()
        c1.set("hotkey", "<f8>")
        c1.set("llm_provider", "openrouter")
        c1.set("openrouter_api_key", "test-key")

        # Create a new Config instance — should load saved values
        c2 = make_config()
        assert c2.hotkey == "<f8>"
        assert c2.get("llm_provider") == "openrouter"
        assert c2.get("openrouter_api_key") == "test-key"

    def test_saved_file_is_valid_json(self, config, tmp_config_path):
        config.set("auto_paste", False)
        with open(tmp_config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["auto_paste"] is False

    def test_load_with_missing_keys_uses_defaults(self, make_config, tmp_config_path):
        # Write a partial config
        tmp_config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_config_path, "w") as f:
            json.dump({"hotkey": "<f5>"}, f)

        c = make_config()
        assert c.hotkey == "<f5>"
        assert c.auto_paste is True  # default
        assert c.get("llm_provider") == "local"  # default


class TestConfigProperties:
    def test_dictations_folder_creates_dir(self, config, tmp_path, monkeypatch):
        folder = str(tmp_path / "my_dictations")
        config.set("dictations_folder", folder)
        result = config.dictations_folder
        assert result == folder
        from pathlib import Path
        assert Path(folder).is_dir()

    def test_sample_rate_property(self, config):
        config.set("sample_rate", 44100)
        assert config.sample_rate == 44100
