"""Tests for ui/hotkey.py — Listener-based hotkey manager."""
import sys
from unittest.mock import MagicMock, patch, call

import pytest


@pytest.fixture(autouse=True)
def mock_pynput(monkeypatch):
    """Provide a mock pynput module so we can test on any platform."""
    mock_keyboard = MagicMock()
    mock_pynput_mod = MagicMock()
    mock_pynput_mod.keyboard = mock_keyboard

    # Create realistic Key enum-like objects
    class FakeKey:
        cmd = "Key.cmd"
        cmd_l = "Key.cmd_l"
        cmd_r = "Key.cmd_r"
        ctrl = "Key.ctrl"
        ctrl_l = "Key.ctrl_l"
        ctrl_r = "Key.ctrl_r"
        alt = "Key.alt"
        alt_l = "Key.alt_l"
        alt_r = "Key.alt_r"
        shift = "Key.shift"
        shift_l = "Key.shift_l"
        shift_r = "Key.shift_r"
        f5 = MagicMock(name="f5")
        f5.name = "f5"
        f8 = MagicMock(name="f8")
        f8.name = "f8"

    class FakeKeyCode:
        def __init__(self, char=None, vk=None):
            self.char = char
            self.vk = vk

    mock_keyboard.Key = FakeKey
    mock_keyboard.KeyCode = FakeKeyCode

    mock_listener = MagicMock()
    mock_keyboard.Listener.return_value = mock_listener

    monkeypatch.setitem(sys.modules, "pynput", mock_pynput_mod)
    monkeypatch.setitem(sys.modules, "pynput.keyboard", mock_keyboard)

    # Force reimport so the module picks up our mocks
    for mod in list(sys.modules):
        if mod.startswith("ui.hotkey"):
            del sys.modules[mod]

    return mock_keyboard


# ── parse_hotkey tests ──────────────────────────────────────────────

class TestParseHotkey:
    def test_cmd_shift_d(self, mock_pynput):
        from ui.hotkey import parse_hotkey
        mods, key = parse_hotkey("<cmd>+<shift>+d")
        assert mods == frozenset({"cmd", "shift"})
        assert key == "d"

    def test_single_function_key(self, mock_pynput):
        from ui.hotkey import parse_hotkey
        mods, key = parse_hotkey("<f5>")
        assert mods == frozenset()
        assert key == "f5"

    def test_ctrl_alt_r(self, mock_pynput):
        from ui.hotkey import parse_hotkey
        mods, key = parse_hotkey("<ctrl>+<alt>+r")
        assert mods == frozenset({"ctrl", "alt"})
        assert key == "r"

    def test_command_alias(self, mock_pynput):
        from ui.hotkey import parse_hotkey
        mods, key = parse_hotkey("<command>+a")
        assert mods == frozenset({"cmd"})
        assert key == "a"

    def test_option_alias(self, mock_pynput):
        from ui.hotkey import parse_hotkey
        mods, key = parse_hotkey("<option>+x")
        assert mods == frozenset({"alt"})
        assert key == "x"


# ── HotkeyManager lifecycle tests ──────────────────────────────────

class TestHotkeyManagerInit:
    def test_stores_hotkey_and_callback(self, mock_pynput):
        from ui.hotkey import HotkeyManager
        cb = lambda: None
        hm = HotkeyManager("<cmd>+<shift>+d", cb)
        assert hm._hotkey_string == "<cmd>+<shift>+d"
        assert hm._callback is cb
        assert hm._listener is None
        assert hm._required_modifiers == frozenset({"cmd", "shift"})
        assert hm._required_key == "d"


class TestHotkeyManagerStart:
    def test_start_creates_listener(self, mock_pynput):
        from ui.hotkey import HotkeyManager
        cb = MagicMock()
        hm = HotkeyManager("<cmd>+<shift>+d", cb)
        hm.start()

        mock_pynput.Listener.assert_called_once()
        assert hm._listener is not None
        hm._listener.start.assert_called_once()

    def test_listener_is_daemon(self, mock_pynput):
        from ui.hotkey import HotkeyManager
        hm = HotkeyManager("<f5>", MagicMock())
        hm.start()
        assert hm._listener.daemon is True


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

        hm.update_hotkey("<cmd>+r")
        assert hm._hotkey_string == "<cmd>+r"
        assert hm._required_modifiers == frozenset({"cmd"})
        assert hm._required_key == "r"
        old_listener.stop.assert_called_once()
        assert mock_pynput.Listener.call_count == 2


# ── Key event simulation tests ──────────────────────────────────────

class TestHotkeyDetection:
    """Test the _on_press / _on_release logic with simulated key events."""

    def _make_manager(self, mock_pynput, hotkey_str, callback):
        from ui.hotkey import HotkeyManager
        hm = HotkeyManager(hotkey_str, callback)
        # Don't actually start a pynput listener; we'll call _on_press directly
        # But we need _normalize_key to work, so we patch it
        return hm

    def test_cmd_shift_d_via_char(self, mock_pynput):
        """Simulate Cmd+Shift+D where key.char='d' is available."""
        from ui.hotkey import HotkeyManager, _normalize_key, _MODIFIER_NAMES

        cb = MagicMock()
        hm = HotkeyManager("<cmd>+<shift>+d", cb)

        Key = mock_pynput.Key
        KeyCode = mock_pynput.KeyCode

        # We need _normalize_key to work with our mocks.
        # Patch it to return predictable values.
        with patch("ui.hotkey._normalize_key") as mock_norm:
            # Press cmd
            mock_norm.return_value = "cmd"
            hm._on_press(Key.cmd)
            assert "cmd" in hm._pressed_modifiers

            # Press shift
            mock_norm.return_value = "shift"
            hm._on_press(Key.shift)
            assert "shift" in hm._pressed_modifiers

            # Press 'd'
            mock_norm.return_value = "d"
            hm._on_press(KeyCode(char="d"))
            cb.assert_called_once()

    def test_wrong_modifiers_dont_trigger(self, mock_pynput):
        from ui.hotkey import HotkeyManager
        Key = mock_pynput.Key

        cb = MagicMock()
        hm = HotkeyManager("<cmd>+<shift>+d", cb)

        with patch("ui.hotkey._normalize_key") as mock_norm:
            # Press only cmd (missing shift)
            mock_norm.return_value = "cmd"
            hm._on_press(Key.cmd)

            mock_norm.return_value = "d"
            hm._on_press(mock_pynput.KeyCode(char="d"))
            cb.assert_not_called()

    def test_no_repeat_while_held(self, mock_pynput):
        from ui.hotkey import HotkeyManager
        Key = mock_pynput.Key

        cb = MagicMock()
        hm = HotkeyManager("<cmd>+d", cb)

        with patch("ui.hotkey._normalize_key") as mock_norm:
            mock_norm.return_value = "cmd"
            hm._on_press(Key.cmd)

            # Press 'd' twice (auto-repeat)
            mock_norm.return_value = "d"
            hm._on_press(mock_pynput.KeyCode(char="d"))
            hm._on_press(mock_pynput.KeyCode(char="d"))
            assert cb.call_count == 1

    def test_release_resets_fired(self, mock_pynput):
        from ui.hotkey import HotkeyManager
        Key = mock_pynput.Key

        cb = MagicMock()
        hm = HotkeyManager("<cmd>+d", cb)

        with patch("ui.hotkey._normalize_key") as mock_norm:
            mock_norm.return_value = "cmd"
            hm._on_press(Key.cmd)

            mock_norm.return_value = "d"
            hm._on_press(mock_pynput.KeyCode(char="d"))
            assert cb.call_count == 1

            # Release 'd'
            mock_norm.return_value = "d"
            hm._on_release(mock_pynput.KeyCode(char="d"))

            # Press again
            mock_norm.return_value = "d"
            hm._on_press(mock_pynput.KeyCode(char="d"))
            assert cb.call_count == 2

    def test_function_key_no_modifiers(self, mock_pynput):
        from ui.hotkey import HotkeyManager
        Key = mock_pynput.Key

        cb = MagicMock()
        hm = HotkeyManager("<f5>", cb)

        with patch("ui.hotkey._normalize_key") as mock_norm:
            mock_norm.return_value = "f5"
            hm._on_press(Key.f5)
            cb.assert_called_once()

    def test_modifier_release_clears_tracking(self, mock_pynput):
        from ui.hotkey import HotkeyManager
        Key = mock_pynput.Key

        cb = MagicMock()
        hm = HotkeyManager("<cmd>+<shift>+d", cb)

        with patch("ui.hotkey._normalize_key") as mock_norm:
            mock_norm.return_value = "cmd"
            hm._on_press(Key.cmd)
            mock_norm.return_value = "shift"
            hm._on_press(Key.shift)
            assert hm._pressed_modifiers == {"cmd", "shift"}

            # Release shift
            mock_norm.return_value = "shift"
            hm._on_release(Key.shift)
            assert hm._pressed_modifiers == {"cmd"}

            # Now 'd' should NOT trigger (shift missing)
            mock_norm.return_value = "d"
            hm._on_press(mock_pynput.KeyCode(char="d"))
            cb.assert_not_called()
