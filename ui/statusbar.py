import logging
import threading

logger = logging.getLogger(__name__)

try:
    import AppKit
    import Foundation
    import objc
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False
    logger.warning("PyObjC not available, status bar disabled")

# Unicode circles for menu bar
# User request: gray=idle, green=recording, yellow=transcribing, red=error
ICON_IDLE = "\u26AA"             # white/gray circle - ready
ICON_RECORDING = "\U0001F7E2"   # green circle - recording
ICON_TRANSCRIBING = "\U0001F7E1" # yellow circle - transcribing
ICON_ERROR = "\U0001F534"       # red circle - error
ICON_LOADING = "\u23F3"         # hourglass - loading model


class StatusBarIcon:
    """Lightweight menu bar status icon using NSStatusBar directly."""

    def __init__(self):
        self._status_item = None

    def setup(self):
        if not HAS_APPKIT:
            return

        status_bar = AppKit.NSStatusBar.systemStatusBar()
        self._status_item = status_bar.statusItemWithLength_(
            AppKit.NSVariableStatusItemLength
        )
        self._status_item.button().setTitle_(ICON_LOADING)
        logger.info("Status bar icon created")

    def set_state(self, state: str):
        if not self._status_item:
            return

        icons = {
            "loading": ICON_LOADING,
            "idle": ICON_IDLE,
            "recording": ICON_RECORDING,
            "transcribing": ICON_TRANSCRIBING,
            "error": ICON_ERROR,
        }
        icon = icons.get(state, ICON_IDLE)

        def _update():
            try:
                self._status_item.button().setTitle_(icon)
                logger.info(f"Status bar: {state} → {icon}")
            except Exception as e:
                logger.error(f"Status bar update failed: {e}")

        # NSStatusItem must be updated on main thread
        if threading.current_thread() is threading.main_thread():
            _update()
        else:
            # Use performSelectorOnMainThread to safely update UI
            try:
                self._status_item.button().performSelectorOnMainThread_withObject_waitUntilDone_(
                    objc.selector(None, selector=b"setTitle:", signature=b"v@:@"),
                    icon,
                    False
                )
                logger.info(f"Status bar: {state} → {icon}")
            except Exception as e:
                logger.warning(f"performSelector failed: {e}, trying direct update")
                _update()

    def remove(self):
        if self._status_item:
            AppKit.NSStatusBar.systemStatusBar().removeStatusItem_(self._status_item)
            self._status_item = None
