import threading
import logging

logger = logging.getLogger(__name__)

try:
    import AppKit
    import Foundation
    HAS_PYOBJC = True
except ImportError:
    HAS_PYOBJC = False


class FloatingIndicator:
    def __init__(self):
        self._window = None
        self._dot_view = None
        if not HAS_PYOBJC:
            logger.warning("PyObjC not available, floating indicator disabled")

    def _ensure_window(self):
        if self._window is not None or not HAS_PYOBJC:
            return

        size = 20
        screen = AppKit.NSScreen.mainScreen()
        screen_frame = screen.frame()
        x = screen_frame.size.width - size - 30
        y = screen_frame.size.height - size - 50

        rect = Foundation.NSMakeRect(x, y, size, size)
        self._window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            AppKit.NSWindowStyleMaskBorderless,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        self._window.setLevel_(AppKit.NSFloatingWindowLevel)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(AppKit.NSColor.clearColor())
        self._window.setIgnoresMouseEvents_(True)
        self._window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
        )

        self._dot_view = AppKit.NSView.alloc().initWithFrame_(
            Foundation.NSMakeRect(0, 0, size, size)
        )
        self._window.contentView().addSubview_(self._dot_view)

    def show(self, color="red"):
        if not HAS_PYOBJC:
            return

        def _show():
            self._ensure_window()
            if color == "red":
                ns_color = AppKit.NSColor.redColor()
            elif color == "yellow":
                ns_color = AppKit.NSColor.yellowColor()
            else:
                ns_color = AppKit.NSColor.greenColor()

            self._dot_view.setWantsLayer_(True)
            layer = self._dot_view.layer()
            layer.setBackgroundColor_(ns_color.CGColor())
            layer.setCornerRadius_(10)
            self._window.orderFront_(None)

        if threading.current_thread() is threading.main_thread():
            _show()
        else:
            AppKit.NSApplication.sharedApplication().performSelectorOnMainThread_withObject_waitUntilDone_(
                Foundation.NSSelectorFromString("doNothing:"), None, False
            )
            _show()

    def hide(self):
        if not HAS_PYOBJC or self._window is None:
            return
        self._window.orderOut_(None)
