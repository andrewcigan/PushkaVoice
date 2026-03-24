import logging
import subprocess
import sys
import time

logger = logging.getLogger(__name__)

# Store the frontmost app before recording starts
_previous_app_bundle = None


def remember_frontmost_app():
    """Remember which app is frontmost (call before recording starts)."""
    global _previous_app_bundle
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        _previous_app_bundle = app.bundleIdentifier()
        logger.info(f"Remembered frontmost app: {app.localizedName()} ({_previous_app_bundle})")
    except Exception as e:
        logger.warning(f"Could not remember frontmost app: {e}")
        _previous_app_bundle = None


def restore_frontmost_app():
    """Restore focus to the app that was frontmost before recording."""
    global _previous_app_bundle
    if sys.platform != "darwin" or not _previous_app_bundle:
        return
    try:
        from AppKit import NSWorkspace, NSRunningApplication
        apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(_previous_app_bundle)
        if apps and len(apps) > 0:
            apps[0].activateWithOptions_(0)
            logger.info(f"Restored focus to: {_previous_app_bundle}")
            time.sleep(0.2)  # Give macOS time to switch focus
        else:
            logger.warning(f"Could not find running app: {_previous_app_bundle}")
    except Exception as e:
        logger.warning(f"Could not restore frontmost app: {e}")
    finally:
        _previous_app_bundle = None


def copy_to_clipboard(text: str):
    """Copy text to the macOS clipboard.

    Uses NSPasteboard (PyObjC) for reliable UTF-8 handling.
    Falls back to pbcopy with explicit UTF-8 locale if PyObjC is unavailable.
    """
    if sys.platform == "darwin":
        try:
            from AppKit import NSPasteboard, NSPasteboardTypeString
            pb = NSPasteboard.generalPasteboard()
            pb.clearContents()
            pb.setString_forType_(text, NSPasteboardTypeString)
            logger.info(f"Copied to clipboard via NSPasteboard: {len(text)} chars")
            return
        except Exception as e:
            logger.warning(f"NSPasteboard failed: {e}, falling back to pbcopy")

    # Fallback: pbcopy with explicit UTF-8 locale
    env = {"LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"}
    process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, env=env)
    process.communicate(text.encode("utf-8"))
    logger.info(f"Copied to clipboard via pbcopy: {len(text)} chars")


def paste_at_cursor():
    # Try CGEvent approach first (doesn't require Accessibility for the calling app)
    try:
        import Quartz
        # Key code 9 = 'v'
        src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
        # Cmd down
        ev_down = Quartz.CGEventCreateKeyboardEvent(src, 9, True)
        Quartz.CGEventSetFlags(ev_down, Quartz.kCGEventFlagMaskCommand)
        # Cmd up
        ev_up = Quartz.CGEventCreateKeyboardEvent(src, 9, False)
        Quartz.CGEventSetFlags(ev_up, Quartz.kCGEventFlagMaskCommand)
        # Post events
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev_down)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev_up)
        logger.info("Auto-pasted via CGEvent Cmd+V")
        return
    except Exception as e:
        logger.warning(f"CGEvent paste failed: {e}, trying osascript...")

    # Fallback to osascript
    result = subprocess.run(
        ["osascript", "-e",
         'tell application "System Events" to keystroke "v" using command down'],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        logger.error(f"Auto-paste failed: {result.stderr.strip()}")
        logger.info("Text is in clipboard — paste manually with Cmd+V")
    else:
        logger.info("Auto-pasted via osascript Cmd+V")


def copy_and_paste(text: str):
    copy_to_clipboard(text)
    restore_frontmost_app()
    time.sleep(0.1)
    paste_at_cursor()
