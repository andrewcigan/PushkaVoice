"""Tests for utils/autostart.py."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from utils.autostart import (
    PLIST_NAME,
    get_plist_content,
    get_plist_path,
    is_installed,
)


class TestGetPlistPath:
    def test_returns_path_object(self):
        result = get_plist_path()
        assert isinstance(result, Path)

    def test_path_ends_with_plist_name(self):
        result = get_plist_path()
        assert result.name == PLIST_NAME

    def test_path_in_launch_agents(self):
        result = get_plist_path()
        assert "LaunchAgents" in str(result)


class TestGetPlistContent:
    def test_returns_valid_plist_xml(self):
        content = get_plist_content()
        assert '<?xml version="1.0"' in content
        assert "<plist" in content
        assert "com.dictation.gigaam" in content

    def test_contains_python_executable(self):
        content = get_plist_content()
        assert sys.executable in content

    def test_contains_app_py(self):
        content = get_plist_content()
        assert "app.py" in content

    def test_run_at_load_true(self):
        content = get_plist_content()
        assert "<key>RunAtLoad</key>" in content
        assert "<true/>" in content


class TestIsInstalled:
    def test_returns_false_when_not_installed(self, tmp_path, monkeypatch):
        fake_path = tmp_path / "nonexistent.plist"
        monkeypatch.setattr("utils.autostart.get_plist_path", lambda: fake_path)
        assert is_installed() is False

    def test_returns_true_when_installed(self, tmp_path, monkeypatch):
        fake_path = tmp_path / "test.plist"
        fake_path.write_text("test")
        monkeypatch.setattr("utils.autostart.get_plist_path", lambda: fake_path)
        assert is_installed() is True


class TestInstallUninstall:
    def test_install_creates_plist(self, tmp_path, monkeypatch):
        plist_path = tmp_path / "LaunchAgents" / PLIST_NAME
        monkeypatch.setattr("utils.autostart.LAUNCH_AGENTS_DIR", tmp_path / "LaunchAgents")
        monkeypatch.setattr("utils.autostart.get_plist_path", lambda: plist_path)
        monkeypatch.setattr("subprocess.run", MagicMock())

        from utils.autostart import install
        install()
        assert plist_path.exists()
        content = plist_path.read_text()
        assert "com.dictation.gigaam" in content

    def test_uninstall_removes_plist(self, tmp_path, monkeypatch):
        plist_path = tmp_path / "test.plist"
        plist_path.write_text("test")
        monkeypatch.setattr("utils.autostart.get_plist_path", lambda: plist_path)
        monkeypatch.setattr("subprocess.run", MagicMock())

        from utils.autostart import uninstall
        uninstall()
        assert not plist_path.exists()

    def test_uninstall_noop_when_not_installed(self, tmp_path, monkeypatch):
        plist_path = tmp_path / "nonexistent.plist"
        monkeypatch.setattr("utils.autostart.get_plist_path", lambda: plist_path)
        mock_run = MagicMock()
        monkeypatch.setattr("subprocess.run", mock_run)

        from utils.autostart import uninstall
        uninstall()  # Should not raise
        mock_run.assert_not_called()
