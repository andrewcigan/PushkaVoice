"""macOS Accessibility permission check and prompt.

Global hotkeys and auto-paste require the Accessibility permission.
This module uses AXIsProcessTrustedWithOptions to both check the
status and open System Settings with our app pre-selected so the user
only needs to flip a toggle.
"""
import logging
import sys

logger = logging.getLogger(__name__)


def is_accessibility_granted() -> bool:
    """Return True if the app already has Accessibility permission."""
    if sys.platform != "darwin":
        return True  # not macOS — assume OK

    try:
        import ApplicationServices as AS
        return AS.AXIsProcessTrusted()
    except Exception as e:
        logger.warning("Cannot check Accessibility: %s", e)
        return True  # can't check — assume OK


def prompt_accessibility() -> bool:
    """Check Accessibility; if not granted, open System Settings for the user.

    Returns True if already granted, False if the prompt was shown.
    """
    if sys.platform != "darwin":
        return True

    try:
        import ApplicationServices as AS
        from CoreFoundation import kAXTrustedCheckOptionPrompt

        # kAXTrustedCheckOptionPrompt = True  → opens System Settings
        options = {kAXTrustedCheckOptionPrompt: True}
        trusted = AS.AXIsProcessTrustedWithOptions(options)
        if trusted:
            logger.info("Accessibility permission granted")
        else:
            logger.info("Accessibility permission NOT granted — prompted user")
        return trusted
    except Exception as e:
        logger.warning("Cannot prompt Accessibility: %s", e)
        return True
