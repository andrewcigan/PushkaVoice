"""Tests for utils/accessibility.py (ctypes-based implementation)."""
import sys
from unittest.mock import MagicMock, patch

import pytest

from utils.accessibility import (
    is_accessibility_granted,
    open_accessibility_settings,
    prompt_accessibility,
    reset_accessibility,
)


class TestIsAccessibilityGranted:
    def test_returns_true_on_non_darwin(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        assert is_accessibility_granted() is True

    def test_returns_true_on_darwin_when_lib_not_found(self, monkeypatch):
        """If ApplicationServices library can't be loaded, assume OK."""
        monkeypatch.setattr(sys, "platform", "darwin")
        with patch("utils.accessibility._get_appservices", return_value=None):
            assert is_accessibility_granted() is True

    def test_returns_true_when_ax_returns_true(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        mock_lib = MagicMock()
        mock_lib.AXIsProcessTrusted.return_value = True
        with patch("utils.accessibility._get_appservices", return_value=mock_lib):
            assert is_accessibility_granted() is True

    def test_returns_false_when_ax_returns_false(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        mock_lib = MagicMock()
        mock_lib.AXIsProcessTrusted.return_value = False
        with patch("utils.accessibility._get_appservices", return_value=mock_lib):
            assert is_accessibility_granted() is False

    def test_returns_true_on_exception(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        mock_lib = MagicMock()
        mock_lib.AXIsProcessTrusted.side_effect = OSError("no framework")
        with patch("utils.accessibility._get_appservices", return_value=mock_lib):
            assert is_accessibility_granted() is True


class TestPromptAccessibility:
    def test_returns_true_on_non_darwin(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        assert prompt_accessibility() is True

    def test_returns_true_when_lib_not_found(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        with patch("utils.accessibility._get_appservices", return_value=None):
            assert prompt_accessibility() is True

    def test_returns_true_when_cf_not_found(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        mock_lib = MagicMock()
        with patch("utils.accessibility._get_appservices", return_value=mock_lib), \
             patch("utils.accessibility._get_corefoundation", return_value=None):
            assert prompt_accessibility() is True

    def test_returns_true_on_exception(self, monkeypatch):
        """Any exception during the ctypes dance should return True (assume OK)."""
        monkeypatch.setattr(sys, "platform", "darwin")
        mock_lib = MagicMock()
        mock_cf = MagicMock()
        # Make c_void_p.in_dll raise
        with patch("utils.accessibility._get_appservices", return_value=mock_lib), \
             patch("utils.accessibility._get_corefoundation", return_value=mock_cf), \
             patch("ctypes.c_void_p") as mock_cvp:
            mock_cvp.in_dll.side_effect = ValueError("symbol not found")
            assert prompt_accessibility() is True


class TestResetAccessibility:
    def test_returns_true_on_non_darwin(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        assert reset_accessibility() is True

    @patch("utils.accessibility.subprocess.run")
    def test_calls_tccutil(self, mock_run, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = reset_accessibility()
        assert result is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "tccutil"
        assert "Accessibility" in args
        assert "com.pushkavoice.app" in args

    @patch("utils.accessibility.subprocess.run")
    def test_returns_false_on_failure(self, mock_run, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        assert reset_accessibility() is False

    @patch("utils.accessibility.subprocess.run")
    def test_returns_false_on_exception(self, mock_run, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        mock_run.side_effect = OSError("no tccutil")
        assert reset_accessibility() is False


class TestOpenAccessibilitySettings:
    def test_noop_on_non_darwin(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        # Should not raise
        open_accessibility_settings()

    @patch("utils.accessibility.subprocess.Popen")
    def test_opens_system_settings(self, mock_popen, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        open_accessibility_settings()
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "open" in args[0]
        assert "Accessibility" in args[1]
