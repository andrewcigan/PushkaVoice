import logging
import subprocess
import time

logger = logging.getLogger(__name__)


def copy_to_clipboard(text: str):
    process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
    process.communicate(text.encode("utf-8"))
    logger.info(f"Copied to clipboard: {len(text)} chars")


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
    time.sleep(0.3)
    paste_at_cursor()
