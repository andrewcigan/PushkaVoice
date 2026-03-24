"""Tests for utils/accessibility.py."""
import sys
from unittest.mock import MagicMock, patch

import pytest


class TestIsAccessibilityGranted:
    def test_returns_true_on_non_darwin(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        from utils.accessibility import is_accessibility_granted
        assert is_accessibility_granted() is True

    @patch.dict(sys.modules, {"ApplicationServices": MagicMock()})
    def test_returns_true_when_trusted(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        mock_as = sys.modules["ApplicationServices"]
        mock_as.AXIsProcessTrusted.return_value = True

        # Force reimport
        if "utils.accessibility" in sys.modules:
            del sys.modules["utils.accessibility"]
        from utils.accessibility import is_accessibility_granted
        assert is_accessibility_granted() is True

    @patch.dict(sys.modules, {"ApplicationServices": MagicMock()})
    def test_returns_false_when_not_trusted(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        mock_as = sys.modules["ApplicationServices"]
        mock_as.AXIsProcessTrusted.return_value = False

        if "utils.accessibility" in sys.modules:
            del sys.modules["utils.accessibility"]
        from utils.accessibility import is_accessibility_granted
        assert is_accessibility_granted() is False

    def test_returns_true_when_check_raises(self, monkeypatch):
        """If ApplicationServices raises, treat as OK (can't check)."""
        monkeypatch.setattr(sys, "platform", "darwin")
        from utils.accessibility import is_accessibility_granted

        with patch("utils.accessibility.AS", create=True) as mock_mod:
            # Simulate import working but call failing
            pass

        # Patch the import inside the function to raise
        with patch.dict(sys.modules, {"ApplicationServices": MagicMock()}) as m:
            mock_as = sys.modules["ApplicationServices"]
            mock_as.AXIsProcessTrusted.side_effect = Exception("no entitlement")
            assert is_accessibility_granted() is True


class TestPromptAccessibility:
    def test_returns_true_on_non_darwin(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        from utils.accessibility import prompt_accessibility
        assert prompt_accessibility() is True

    @patch.dict(sys.modules, {
        "ApplicationServices": MagicMock(),
        "CoreFoundation": MagicMock(),
    })
    def test_opens_settings_when_not_trusted(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        mock_as = sys.modules["ApplicationServices"]
        mock_as.AXIsProcessTrustedWithOptions.return_value = False

        if "utils.accessibility" in sys.modules:
            del sys.modules["utils.accessibility"]
        from utils.accessibility import prompt_accessibility
        result = prompt_accessibility()
        assert result is False
        mock_as.AXIsProcessTrustedWithOptions.assert_called_once()

    @patch.dict(sys.modules, {
        "ApplicationServices": MagicMock(),
        "CoreFoundation": MagicMock(),
    })
    def test_returns_true_when_already_trusted(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        mock_as = sys.modules["ApplicationServices"]
        mock_as.AXIsProcessTrustedWithOptions.return_value = True

        if "utils.accessibility" in sys.modules:
            del sys.modules["utils.accessibility"]
        from utils.accessibility import prompt_accessibility
        assert prompt_accessibility() is True
