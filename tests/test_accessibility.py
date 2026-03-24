"""Tests for utils/accessibility.py (ctypes-based implementation)."""
import sys
from unittest.mock import MagicMock, patch

import pytest

from utils.accessibility import is_accessibility_granted, prompt_accessibility


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
