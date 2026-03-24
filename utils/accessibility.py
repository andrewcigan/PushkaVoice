"""macOS Accessibility permission check and prompt.

Global hotkeys and auto-paste require the Accessibility permission.
Uses ctypes to call the macOS C API directly, avoiding issues with
PyInstaller-bundled PyObjC where CoreFoundation constants may be missing.
"""
import ctypes
import ctypes.util
import logging
import sys

logger = logging.getLogger(__name__)

# Cache loaded libraries
_appservices_lib = None
_cf_lib = None


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
    """Check Accessibility; if not granted, open System Settings for the user.

    Uses AXIsProcessTrustedWithOptions via ctypes to avoid dependency on
    PyObjC CoreFoundation bindings (which may be incomplete in PyInstaller bundles).

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

        # Get the kAXTrustedCheckOptionPrompt key string
        # It's a CFStringRef constant exported by ApplicationServices
        try:
            kAXTrustedCheckOptionPrompt = ctypes.c_void_p.in_dll(
                lib, "kAXTrustedCheckOptionPrompt"
            )
        except (ValueError, AttributeError):
            logger.warning("kAXTrustedCheckOptionPrompt symbol not found")
            return True

        # Create CFBoolean True
        kCFBooleanTrue = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue")

        # Create CFDictionary with {kAXTrustedCheckOptionPrompt: kCFBooleanTrue}
        cf.CFDictionaryCreateMutable.restype = ctypes.c_void_p
        cf.CFDictionaryCreateMutable.argtypes = [
            ctypes.c_void_p,  # allocator
            ctypes.c_long,    # capacity
            ctypes.c_void_p,  # keyCallBacks
            ctypes.c_void_p,  # valueCallBacks
        ]

        # Get default callbacks
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
            ctypes.c_void_p,  # dict
            ctypes.c_void_p,  # key
            ctypes.c_void_p,  # value
        ]
        cf.CFDictionarySetValue(
            options,
            kAXTrustedCheckOptionPrompt,
            kCFBooleanTrue,
        )

        # Call AXIsProcessTrustedWithOptions
        lib.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
        lib.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
        trusted = lib.AXIsProcessTrustedWithOptions(options)

        # Release the dictionary
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
