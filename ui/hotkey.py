"""Global hotkey listener using pynput.keyboard.Listener with manual key tracking.

We avoid pynput's GlobalHotKeys because it silently fails on macOS when
modifier keys are held (key.char becomes None).  Instead we use a raw
Listener, normalise every key event to a canonical name, track pressed
modifiers ourselves, and fire the callback when the combination matches.
"""
import logging
import sys
import threading

logger = logging.getLogger(__name__)

try:
    from pynput import keyboard
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False
    logger.warning("pynput not available — global hotkeys disabled")

# ── macOS virtual-key-code → character mapping ──────────────────────
# When modifier keys (especially Cmd) are held, pynput reports
# KeyCode(vk=…, char=None).  We need the vk table to recover the
# intended character.
_VK_MAP = {
    0: 'a', 1: 's', 2: 'd', 3: 'f', 4: 'h', 5: 'g', 6: 'z', 7: 'x',
    8: 'c', 9: 'v', 11: 'b', 12: 'q', 13: 'w', 14: 'e', 15: 'r',
    16: 'y', 17: 't', 18: '1', 19: '2', 20: '3', 21: '4', 22: '6',
    23: '5', 24: '=', 25: '9', 26: '7', 27: '-', 28: '8', 29: '0',
    30: ']', 31: 'o', 32: 'u', 33: '[', 34: 'i', 35: 'p',
    37: 'l', 38: 'j', 39: "'", 40: 'k', 41: ';', 42: '\\',
    43: ',', 44: '/', 45: 'n', 46: 'm', 47: '.', 49: 'space',
}

# ── Modifier key → canonical name ──────────────────────────────────
_MODIFIER_NAMES = {'cmd', 'ctrl', 'alt', 'shift'}


def _build_modifier_map():
    """Build pynput Key → canonical modifier name mapping."""
    if not HAS_PYNPUT:
        return {}
    m = {}
    for attr, name in [
        ('cmd', 'cmd'), ('cmd_l', 'cmd'), ('cmd_r', 'cmd'),
        ('ctrl', 'ctrl'), ('ctrl_l', 'ctrl'), ('ctrl_r', 'ctrl'),
        ('alt', 'alt'), ('alt_l', 'alt'), ('alt_r', 'alt'),
        ('shift', 'shift'), ('shift_l', 'shift'), ('shift_r', 'shift'),
    ]:
        key = getattr(keyboard.Key, attr, None)
        if key is not None:
            m[key] = name
    return m


_MODIFIER_MAP = _build_modifier_map()


def _normalize_key(key):
    """Convert a pynput key event to a canonical lowercase string.

    Returns a modifier name ('cmd', 'ctrl', 'alt', 'shift'),
    a character ('d', '1', 'space'), a special key name ('f5'),
    or None if unrecognised.
    """
    if not HAS_PYNPUT:
        return None

    # Modifier keys
    if isinstance(key, keyboard.Key):
        mod = _MODIFIER_MAP.get(key)
        if mod:
            return mod
        # Non-modifier special keys (F1–F20, esc, tab, …)
        return key.name.lower() if hasattr(key, 'name') else None

    if isinstance(key, keyboard.KeyCode):
        # When no modifier obscures the character
        if key.char is not None:
            return key.char.lower()
        # Fallback: virtual key code (macOS)
        if key.vk is not None:
            return _VK_MAP.get(key.vk)

    return None


def parse_hotkey(hotkey_string: str):
    """Parse a hotkey string like '<cmd>+<shift>+d' into (frozenset, str).

    Returns (modifier_names: frozenset[str], key: str | None).
    """
    parts = hotkey_string.lower().split('+')
    modifiers = set()
    key = None
    for part in parts:
        part = part.strip().strip('<>')
        if part in ('cmd', 'command', 'super'):
            modifiers.add('cmd')
        elif part in ('ctrl', 'control'):
            modifiers.add('ctrl')
        elif part in ('alt', 'option'):
            modifiers.add('alt')
        elif part in ('shift',):
            modifiers.add('shift')
        elif part:
            key = part  # e.g. 'd', 'f5', 'space'
    return frozenset(modifiers), key


class HotkeyManager:
    """Listens for a global hotkey and calls *callback* when it fires."""

    def __init__(self, hotkey_string: str, callback):
        self._hotkey_string = hotkey_string
        self._callback = callback
        self._listener = None
        self._required_modifiers, self._required_key = parse_hotkey(hotkey_string)
        self._pressed_modifiers: set[str] = set()
        self._lock = threading.Lock()
        self._fired = False  # prevent auto-repeat while held

    # ── public API ──────────────────────────────────────────────────

    def start(self):
        if not HAS_PYNPUT:
            logger.error("Cannot start hotkey listener — pynput not installed")
            return

        try:
            self._pressed_modifiers.clear()
            self._fired = False
            self._listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
            self._listener.daemon = True
            self._listener.start()
            logger.info(
                "Hotkey listener started: %s  (modifiers=%s, key=%s)",
                self._hotkey_string, self._required_modifiers, self._required_key,
            )
        except Exception as e:
            logger.error("Failed to start hotkey listener: %s", e)

    def stop(self):
        if self._listener:
            self._listener.stop()
            self._listener = None

    def update_hotkey(self, new_hotkey_string: str):
        self.stop()
        self._hotkey_string = new_hotkey_string
        self._required_modifiers, self._required_key = parse_hotkey(new_hotkey_string)
        self.start()

    # ── internal ────────────────────────────────────────────────────

    def _on_press(self, key):
        with self._lock:
            name = _normalize_key(key)
            if name is None:
                return

            if name in _MODIFIER_NAMES:
                self._pressed_modifiers.add(name)
                return

            # Non-modifier key — check if it matches the hotkey
            if name == self._required_key \
                    and self._pressed_modifiers == self._required_modifiers \
                    and not self._fired:
                self._fired = True
                logger.info("Hotkey triggered: %s", self._hotkey_string)
                try:
                    self._callback()
                except Exception as e:
                    logger.error("Hotkey callback error: %s", e)

    def _on_release(self, key):
        with self._lock:
            name = _normalize_key(key)
            if name is None:
                return

            if name in _MODIFIER_NAMES:
                self._pressed_modifiers.discard(name)
            # Reset the repeat guard so the hotkey can fire again
            self._fired = False
