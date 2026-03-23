"""Tests for ui/hotkey.py."""
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_pynput(monkeypatch):
    """Mock pynput module."""
    mock_keyboard = MagicMock()
    mock_pynput_mod = MagicMock()
    mock_pynput_mod.keyboard = mock_keyboard

    mock_listener = MagicMock()
    mock_keyboard.GlobalHotKeys.return_value = mock_listener

    monkeypatch.setitem(sys.modules, "pynput", mock_pynput_mod)
    monkeypatch.setitem(sys.modules, "pynput.keyboard", mock_keyboard)

    # Force reimport
    if "ui.hotkey" in sys.modules:
        del sys.modules["ui.hotkey"]

    return mock_keyboard


class TestHotkeyManagerInit:
    def test_stores_hotkey_and_callback(self):
        from ui.hotkey import HotkeyManager
        cb = lambda: None
        hm = HotkeyManager("<cmd>+<shift>+d", cb)
        assert hm._hotkey_string == "<cmd>+<shift>+d"
        assert hm._callback is cb
        assert hm._listener is None


class TestHotkeyManagerStart:
    def test_start_creates_listener(self, mock_pynput):
        from ui.hotkey import HotkeyManager
        cb = MagicMock()
        hm = HotkeyManager("<cmd>+<shift>+d", cb)
        hm.start()

        mock_pynput.GlobalHotKeys.assert_called_once()
        call_args = mock_pynput.GlobalHotKeys.call_args[0][0]
        assert "<cmd>+<shift>+d" in call_args

    def test_start_starts_listener(self, mock_pynput):
        from ui.hotkey import HotkeyManager
        hm = HotkeyManager("<f5>", MagicMock())
        hm.start()
        assert hm._listener is not None
        hm._listener.start.assert_called_once()


class TestHotkeyManagerStop:
    def test_stop_stops_listener(self, mock_pynput):
        from ui.hotkey import HotkeyManager
        hm = HotkeyManager("<f5>", MagicMock())
        hm.start()
        listener = hm._listener
        hm.stop()
        listener.stop.assert_called_once()
        assert hm._listener is None

    def test_stop_noop_if_not_started(self, mock_pynput):
        from ui.hotkey import HotkeyManager
        hm = HotkeyManager("<f5>", MagicMock())
        hm.stop()  # should not raise


class TestHotkeyManagerUpdate:
    def test_update_restarts_with_new_hotkey(self, mock_pynput):
        from ui.hotkey import HotkeyManager
        hm = HotkeyManager("<f5>", MagicMock())
        hm.start()
        old_listener = hm._listener

        hm.update_hotkey("<f8>")
        assert hm._hotkey_string == "<f8>"
        old_listener.stop.assert_called_once()
        # A new listener was created
        assert mock_pynput.GlobalHotKeys.call_count == 2
