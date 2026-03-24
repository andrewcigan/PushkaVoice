"""Global hotkey listener using macOS CGEventTap (Quartz).

Uses CGEventTap directly instead of pynput to avoid TSMGetInputSourceProperty
crash on macOS 15+ where TSM functions must be called from the main thread.
CGEventTap runs on its own CFRunLoop thread and uses virtual keycodes directly,
so it never touches TSM.

Falls back to pynput on non-macOS platforms.
"""
import logging
import sys
import threading
import time

logger = logging.getLogger(__name__)

# ── macOS virtual-key-code → character mapping ──────────────────────
_VK_MAP = {
    0: 'a', 1: 's', 2: 'd', 3: 'f', 4: 'h', 5: 'g', 6: 'z', 7: 'x',
    8: 'c', 9: 'v', 11: 'b', 12: 'q', 13: 'w', 14: 'e', 15: 'r',
    16: 'y', 17: 't', 18: '1', 19: '2', 20: '3', 21: '4', 22: '6',
    23: '5', 24: '=', 25: '9', 26: '7', 27: '-', 28: '8', 29: '0',
    30: ']', 31: 'o', 32: 'u', 33: '[', 34: 'i', 35: 'p',
    37: 'l', 38: 'j', 39: "'", 40: 'k', 41: ';', 42: '\\',
    43: ',', 44: '/', 45: 'n', 46: 'm', 47: '.', 49: 'space',
}

# Modifier flag masks from CGEvent
_kCGEventFlagMaskCommand = 0x00100000
_kCGEventFlagMaskShift = 0x00020000
_kCGEventFlagMaskAlternate = 0x00080000
_kCGEventFlagMaskControl = 0x00040000

_MODIFIER_NAMES = {'cmd', 'ctrl', 'alt', 'shift'}


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


def _get_modifiers_from_flags(flags):
    """Extract modifier set from CGEvent flags."""
    mods = set()
    if flags & _kCGEventFlagMaskCommand:
        mods.add('cmd')
    if flags & _kCGEventFlagMaskShift:
        mods.add('shift')
    if flags & _kCGEventFlagMaskAlternate:
        mods.add('alt')
    if flags & _kCGEventFlagMaskControl:
        mods.add('ctrl')
    return mods


class HotkeyManager:
    """Listens for a global hotkey and calls *callback* when it fires."""

    def __init__(self, hotkey_string: str, callback):
        self._hotkey_string = hotkey_string
        self._callback = callback
        self._listener_thread = None
        self._run_loop = None
        self._run_loop_source = None
        self._required_modifiers, self._required_key = parse_hotkey(hotkey_string)
        self._fired = False
        self._running = False
        self._lock = threading.Lock()

    def start(self):
        if sys.platform != "darwin":
            logger.warning("CGEventTap hotkeys only supported on macOS")
            return

        try:
            self._running = True
            self._fired = False
            self._listener_thread = threading.Thread(
                target=self._run_event_tap,
                daemon=True,
                name="HotkeyListener",
            )
            self._listener_thread.start()
            logger.info(
                "Hotkey listener started: %s  (modifiers=%s, key=%s)",
                self._hotkey_string, self._required_modifiers, self._required_key,
            )
        except Exception as e:
            logger.error("Failed to start hotkey listener: %s", e)

    def stop(self):
        self._running = False
        if self._run_loop is not None:
            try:
                import Quartz
                Quartz.CFRunLoopStop(self._run_loop)
            except Exception:
                pass
        self._run_loop = None
        self._run_loop_source = None
        self._listener_thread = None

    def restart(self):
        logger.info("Restarting hotkey listener...")
        self.stop()
        self.start()

    def update_hotkey(self, new_hotkey_string: str):
        self.stop()
        self._hotkey_string = new_hotkey_string
        self._required_modifiers, self._required_key = parse_hotkey(new_hotkey_string)
        self.start()

    def _run_event_tap(self):
        """Run CGEventTap on a background thread with its own CFRunLoop."""
        try:
            import Quartz

            def callback(proxy, event_type, event, refcon):
                try:
                    # Re-enable tap if it gets disabled
                    if event_type == Quartz.kCGEventTapDisabledByTimeout:
                        logger.warning("Event tap disabled by timeout, re-enabling...")
                        if self._tap:
                            Quartz.CGEventTapEnable(self._tap, True)
                        return event
                    if event_type == Quartz.kCGEventTapDisabledByUserInput:
                        return event

                    keycode = Quartz.CGEventGetIntegerValueField(
                        event, Quartz.kCGKeyboardEventKeycode
                    )
                    flags = Quartz.CGEventGetFlags(event)

                    if event_type == Quartz.kCGEventKeyDown:
                        key_name = _VK_MAP.get(keycode)
                        if key_name is None:
                            return event

                        mods = _get_modifiers_from_flags(flags)

                        with self._lock:
                            if (key_name == self._required_key
                                    and mods == self._required_modifiers
                                    and not self._fired):
                                self._fired = True
                                logger.info("Hotkey triggered: %s", self._hotkey_string)
                                try:
                                    self._callback()
                                except Exception as e:
                                    logger.error("Hotkey callback error: %s", e)

                    elif event_type == Quartz.kCGEventKeyUp:
                        with self._lock:
                            self._fired = False

                except Exception as e:
                    logger.error("Event tap callback error: %s", e)

                return event

            # Create event tap for key down and key up events
            event_mask = (
                Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
                | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
            )

            # Retry CGEventTapCreate with backoff — macOS may need time to
            # propagate Accessibility permission after AXIsProcessTrusted()
            # already returns True.
            max_retries = 5
            retry_delays = [0, 1, 2, 3, 5]  # seconds
            self._tap = None
            for attempt in range(max_retries):
                if not self._running:
                    return
                if attempt > 0:
                    delay = retry_delays[attempt]
                    logger.info(
                        "Retrying CGEventTapCreate in %ds (attempt %d/%d)...",
                        delay, attempt + 1, max_retries,
                    )
                    time.sleep(delay)
                    if not self._running:
                        return

                self._tap = Quartz.CGEventTapCreate(
                    Quartz.kCGSessionEventTap,
                    Quartz.kCGHeadInsertEventTap,
                    Quartz.kCGEventTapOptionListenOnly,  # passive listener
                    event_mask,
                    callback,
                    None,
                )
                if self._tap is not None:
                    if attempt > 0:
                        logger.info("CGEventTapCreate succeeded on attempt %d", attempt + 1)
                    break
                logger.warning(
                    "CGEventTapCreate returned None (attempt %d/%d)",
                    attempt + 1, max_retries,
                )

            if self._tap is None:
                logger.error(
                    "Failed to create CGEventTap after %d attempts — "
                    "Accessibility permission required. "
                    "Hotkeys will not work until permission is granted.",
                    max_retries,
                )
                return

            self._run_loop_source = Quartz.CFMachPortCreateRunLoopSource(
                None, self._tap, 0
            )
            self._run_loop = Quartz.CFRunLoopGetCurrent()
            Quartz.CFRunLoopAddSource(
                self._run_loop,
                self._run_loop_source,
                Quartz.kCFRunLoopDefaultMode,
            )
            Quartz.CGEventTapEnable(self._tap, True)

            logger.info("CGEventTap created and running")

            # Run the loop — blocks until stop() calls CFRunLoopStop
            Quartz.CFRunLoopRun()

            logger.info("CGEventTap run loop exited")

        except ImportError:
            logger.error("Quartz not available — hotkeys disabled on this system")
        except Exception as e:
            logger.error("CGEventTap failed: %s", e, exc_info=True)
