"""macOS Accessibility and Input Monitoring permission management.

Global hotkeys (CGEventTap) require **Input Monitoring** permission.
Auto-paste (CGEvent posting) requires **Accessibility** permission.

These are two separate TCC services:
  - Accessibility  → AXIsProcessTrusted()
  - Input Monitoring (ListenEvent) → CGPreflightListenEventAccess()

Uses ctypes to call the macOS C API directly, avoiding issues with
PyInstaller-bundled PyObjC where CoreFoundation constants may be missing.

When the app is rebuilt with ad-hoc signing, macOS treats it as a new app
because the code signature changes.  Old TCC entries become stale.
Use reset_permissions() to clear them before re-prompting.
"""
import ctypes
import ctypes.util
import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

BUNDLE_ID = "com.pushkavoice.app"

# Cache loaded libraries
_appservices_lib = None
_cf_lib = None
_cg_lib = None


def _get_appservices():
    """Load ApplicationServices framework via ctypes."""
    global _appservices_lib
    if _appservices_lib is None:
        path = ctypes.util.find_library("ApplicationServices")
        if path:
            _appservices_lib = ctypes.cdll.LoadLibrary(path)
    return _appservices_lib


def _get_corefoundation():
    """Load CoreFoundation framework via ctypes."""
    global _cf_lib
    if _cf_lib is None:
        path = ctypes.util.find_library("CoreFoundation")
        if path:
            _cf_lib = ctypes.cdll.LoadLibrary(path)
    return _cf_lib


def _get_coregraphics():
    """Load CoreGraphics framework via ctypes."""
    global _cg_lib
    if _cg_lib is None:
        path = ctypes.util.find_library("CoreGraphics")
        if path:
            _cg_lib = ctypes.cdll.LoadLibrary(path)
    return _cg_lib


# ── Accessibility (needed for auto-paste via CGEvent Cmd+V) ──────────


def is_accessibility_granted() -> bool:
    """Return True if the app already has Accessibility permission."""
    if sys.platform != "darwin":
        logger.debug("Not macOS, skipping accessibility check")
        return True

    try:
        lib = _get_appservices()
        if lib is None:
            logger.warning("Cannot load ApplicationServices framework")
            return True
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        result = lib.AXIsProcessTrusted()
        logger.debug("AXIsProcessTrusted() = %s", result)
        return result
    except Exception as e:
        logger.warning("Cannot check Accessibility: %s", e)
        return True


def prompt_accessibility() -> bool:
    """Check Accessibility; if not granted, show macOS prompt.

    Returns True if already granted, False if the prompt was shown.
    """
    if sys.platform != "darwin":
        return True

    try:
        lib = _get_appservices()
        cf = _get_corefoundation()
        if lib is None or cf is None:
            logger.warning("Cannot load macOS frameworks for accessibility prompt")
            return True

        try:
            kAXTrustedCheckOptionPrompt = ctypes.c_void_p.in_dll(
                lib, "kAXTrustedCheckOptionPrompt"
            )
        except (ValueError, AttributeError):
            logger.warning("kAXTrustedCheckOptionPrompt symbol not found")
            return True

        kCFBooleanTrue = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue")

        cf.CFDictionaryCreateMutable.restype = ctypes.c_void_p
        cf.CFDictionaryCreateMutable.argtypes = [
            ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p,
        ]
        kCFTypeDictionaryKeyCallBacks = ctypes.c_void_p.in_dll(
            cf, "kCFTypeDictionaryKeyCallBacks"
        )
        kCFTypeDictionaryValueCallBacks = ctypes.c_void_p.in_dll(
            cf, "kCFTypeDictionaryValueCallBacks"
        )

        options = cf.CFDictionaryCreateMutable(
            None, 1,
            ctypes.byref(kCFTypeDictionaryKeyCallBacks),
            ctypes.byref(kCFTypeDictionaryValueCallBacks),
        )

        cf.CFDictionarySetValue.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ]
        cf.CFDictionarySetValue(
            options, kAXTrustedCheckOptionPrompt, kCFBooleanTrue,
        )

        lib.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
        lib.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
        trusted = lib.AXIsProcessTrustedWithOptions(options)

        cf.CFRelease.argtypes = [ctypes.c_void_p]
        cf.CFRelease(options)

        if trusted:
            logger.info("Accessibility permission granted")
        else:
            logger.info("Accessibility permission NOT granted — prompted user")
        return bool(trusted)

    except Exception as e:
        logger.warning("Cannot prompt Accessibility: %s", e)
        return True


# ── Input Monitoring (needed for CGEventTap / hotkeys) ───────────────


def is_input_monitoring_granted() -> bool:
    """Return True if Input Monitoring permission is granted.

    Uses CGPreflightListenEventAccess() (macOS 10.15+).
    This is the permission CGEventTapCreate actually requires.
    """
    if sys.platform != "darwin":
        return True

    try:
        cg = _get_coregraphics()
        if cg is None:
            logger.warning("Cannot load CoreGraphics framework")
            return True
        cg.CGPreflightListenEventAccess.restype = ctypes.c_bool
        result = cg.CGPreflightListenEventAccess()
        logger.debug("CGPreflightListenEventAccess() = %s", result)
        return result
    except (AttributeError, OSError) as e:
        # CGPreflightListenEventAccess not available (pre-10.15)
        logger.debug("CGPreflightListenEventAccess not available: %s", e)
        return is_accessibility_granted()  # fallback
    except Exception as e:
        logger.warning("Cannot check Input Monitoring: %s", e)
        return True


def request_input_monitoring() -> bool:
    """Request Input Monitoring permission from macOS.

    Uses CGRequestListenEventAccess() (macOS 10.15+).
    Shows the system dialog prompting the user to grant Input Monitoring.
    Returns True if already granted.
    """
    if sys.platform != "darwin":
        return True

    try:
        cg = _get_coregraphics()
        if cg is None:
            logger.warning("Cannot load CoreGraphics framework")
            return True
        cg.CGRequestListenEventAccess.restype = ctypes.c_bool
        result = cg.CGRequestListenEventAccess()
        if result:
            logger.info("Input Monitoring permission granted")
        else:
            logger.info("Input Monitoring permission NOT granted — prompted user")
        return result
    except (AttributeError, OSError) as e:
        logger.debug("CGRequestListenEventAccess not available: %s", e)
        return prompt_accessibility()  # fallback
    except Exception as e:
        logger.warning("Cannot request Input Monitoring: %s", e)
        return True


# ── Combined checks ──────────────────────────────────────────────────


def are_all_permissions_granted() -> bool:
    """Check both Accessibility and Input Monitoring."""
    ax = is_accessibility_granted()
    im = is_input_monitoring_granted()
    logger.debug("Permissions: accessibility=%s, input_monitoring=%s", ax, im)
    return ax and im


def request_all_permissions() -> dict:
    """Request both Accessibility and Input Monitoring permissions.

    Returns dict with status of each.
    """
    ax = prompt_accessibility()
    im = request_input_monitoring()
    return {"accessibility": ax, "input_monitoring": im}


# ── TCC Reset (for after app updates with new code signature) ────────


def reset_accessibility() -> bool:
    """Clear stale Accessibility TCC entries for our bundle ID."""
    if sys.platform != "darwin":
        return True

    try:
        result = subprocess.run(
            ["tccutil", "reset", "Accessibility", BUNDLE_ID],
            capture_output=True, text=True, timeout=10,
        )
        logger.info(
            "tccutil reset Accessibility %s → returncode=%d, stdout=%r, stderr=%r",
            BUNDLE_ID, result.returncode, result.stdout.strip(), result.stderr.strip(),
        )
        return result.returncode == 0
    except Exception as e:
        logger.warning("tccutil reset Accessibility failed: %s", e)
        return False


def reset_input_monitoring() -> bool:
    """Clear stale Input Monitoring (ListenEvent) TCC entries."""
    if sys.platform != "darwin":
        return True

    try:
        result = subprocess.run(
            ["tccutil", "reset", "ListenEvent", BUNDLE_ID],
            capture_output=True, text=True, timeout=10,
        )
        logger.info(
            "tccutil reset ListenEvent %s → returncode=%d, stdout=%r, stderr=%r",
            BUNDLE_ID, result.returncode, result.stdout.strip(), result.stderr.strip(),
        )
        return result.returncode == 0
    except Exception as e:
        logger.warning("tccutil reset ListenEvent failed: %s", e)
        return False


def reset_all_permissions() -> bool:
    """Reset both Accessibility and Input Monitoring TCC entries."""
    ax = reset_accessibility()
    im = reset_input_monitoring()
    return ax and im


# ── Settings ─────────────────────────────────────────────────────────


def open_accessibility_settings():
    """Open System Settings directly to the Accessibility pane."""
    if sys.platform != "darwin":
        return

    try:
        subprocess.Popen([
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        ])
        logger.info("Opened System Settings → Accessibility")
    except Exception as e:
        logger.warning("Cannot open System Settings: %s", e)


def open_input_monitoring_settings():
    """Open System Settings directly to the Input Monitoring pane."""
    if sys.platform != "darwin":
        return

    try:
        subprocess.Popen([
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
        ])
        logger.info("Opened System Settings → Input Monitoring")
    except Exception as e:
        logger.warning("Cannot open System Settings: %s", e)
