#!/usr/bin/env python3
import atexit
import faulthandler
import logging
import os
import signal
import sys
import threading
import time
import traceback
from pathlib import Path

# Fix SSL certificates for PyInstaller bundles on macOS.
# Bundled Python cannot find system CA certs, so we point OpenSSL
# at the certifi CA bundle before any HTTPS requests are made.
try:
    import certifi
    import ssl
    os.environ.setdefault('SSL_CERT_FILE', certifi.where())
    os.environ.setdefault('REQUESTS_CA_BUNDLE', certifi.where())
    # Patch default SSL context so urllib.request.urlopen (used by gigaam) trusts certs
    ssl._create_default_https_context = lambda: ssl.create_default_context(
        cafile=certifi.where()
    )
except ImportError:
    pass  # certifi not available; system certs will be used

# Detect PyInstaller bundled mode
if getattr(sys, 'frozen', False):
    # Running as PyInstaller bundle
    APP_DIR = Path(sys._MEIPASS)
    DATA_DIR = Path.home() / ".pushkavoice"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
else:
    APP_DIR = Path(__file__).parent
    DATA_DIR = APP_DIR

sys.path.insert(0, str(APP_DIR))

# Setup logging — DEBUG level to catch everything
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(DATA_DIR / "dictation.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ── Crash logging ────────────────────────────────────────────────
CRASH_LOG = DATA_DIR / "crash.log"

# Enable faulthandler for segfaults and fatal signals
try:
    _fault_file = open(CRASH_LOG, "a")
    faulthandler.enable(file=_fault_file, all_threads=True)
except Exception:
    faulthandler.enable()


def _crash_excepthook(exc_type, exc_value, exc_tb):
    """Global exception handler — writes to crash.log and stderr."""
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    crash_msg = f"\n{'='*60}\nUNCAUGHT EXCEPTION at {ts}\n{msg}{'='*60}\n"
    try:
        with open(CRASH_LOG, "a") as f:
            f.write(crash_msg)
    except Exception:
        pass
    logger.critical("UNCAUGHT EXCEPTION:\n%s", msg)
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _crash_excepthook


def _thread_excepthook(args):
    """Catch unhandled exceptions in threads."""
    msg = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    crash_msg = f"\n{'='*60}\nTHREAD EXCEPTION ({args.thread}) at {ts}\n{msg}{'='*60}\n"
    try:
        with open(CRASH_LOG, "a") as f:
            f.write(crash_msg)
    except Exception:
        pass
    logger.critical("THREAD EXCEPTION in %s:\n%s", args.thread, msg)


threading.excepthook = _thread_excepthook


def _signal_handler(signum, frame):
    """Log when the process receives a signal (SIGTERM, SIGINT, etc.)."""
    sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
    msg = f"Received signal {sig_name} ({signum})"
    logger.warning(msg)
    try:
        with open(CRASH_LOG, "a") as f:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"\n{'='*60}\nSIGNAL {sig_name} at {ts}\n")
            if frame:
                f.write("".join(traceback.format_stack(frame)))
            f.write(f"{'='*60}\n")
    except Exception:
        pass
    sys.exit(128 + signum)


for _sig in (signal.SIGTERM, signal.SIGINT):
    signal.signal(_sig, _signal_handler)
if hasattr(signal, 'SIGHUP'):
    signal.signal(signal.SIGHUP, _signal_handler)


def _atexit_handler():
    logger.info("App exiting (atexit). PID=%d", os.getpid())
    try:
        with open(CRASH_LOG, "a") as f:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"\nAPP EXIT (atexit) at {ts}, PID={os.getpid()}\n")
    except Exception:
        pass


atexit.register(_atexit_handler)


def _log_app_identity():
    """Log everything about how macOS sees this app."""
    logger.info("="*60)
    logger.info("APP IDENTITY DIAGNOSTICS")
    logger.info("  PID: %d", os.getpid())
    logger.info("  sys.executable: %s", sys.executable)
    logger.info("  sys.argv: %s", sys.argv)
    logger.info("  frozen: %s", getattr(sys, 'frozen', False))
    logger.info("  _MEIPASS: %s", getattr(sys, '_MEIPASS', 'N/A'))
    logger.info("  CWD: %s", os.getcwd())
    logger.info("  APP_DIR: %s", APP_DIR)
    logger.info("  DATA_DIR: %s", DATA_DIR)

    if getattr(sys, 'frozen', False):
        # Find .app bundle
        exe_path = Path(sys.executable).resolve()
        logger.info("  Resolved executable: %s", exe_path)
        for parent in exe_path.parents:
            if parent.suffix == '.app':
                logger.info("  .app bundle: %s", parent)
                logger.info("  .app bundle name: %s", parent.name)
                # Read Info.plist
                plist_path = parent / "Contents" / "Info.plist"
                if plist_path.exists():
                    try:
                        import plistlib
                        with open(plist_path, "rb") as f:
                            plist = plistlib.load(f)
                        logger.info("  CFBundleName: %s", plist.get('CFBundleName', 'NOT SET'))
                        logger.info("  CFBundleDisplayName: %s", plist.get('CFBundleDisplayName', 'NOT SET'))
                        logger.info("  CFBundleIdentifier: %s", plist.get('CFBundleIdentifier', 'NOT SET'))
                        logger.info("  CFBundleExecutable: %s", plist.get('CFBundleExecutable', 'NOT SET'))
                        logger.info("  CFBundleVersion: %s", plist.get('CFBundleVersion', 'NOT SET'))
                    except Exception as e:
                        logger.error("  Failed to read Info.plist: %s", e)
                else:
                    logger.warning("  Info.plist NOT FOUND at %s", plist_path)
                break
        else:
            logger.warning("  Could not find .app bundle in parents of %s", exe_path)

    # Check process name as macOS sees it
    if sys.platform == "darwin":
        try:
            import subprocess
            result = subprocess.run(
                ["ps", "-p", str(os.getpid()), "-o", "comm="],
                capture_output=True, text=True, timeout=5,
            )
            logger.info("  Process name (ps): %s", result.stdout.strip())
        except Exception as e:
            logger.warning("  Could not get process name: %s", e)

        # Check LaunchServices registration
        try:
            import subprocess
            result = subprocess.run(
                ["mdfind", "kMDItemCFBundleIdentifier == 'com.pushkavoice.app'"],
                capture_output=True, text=True, timeout=10,
            )
            paths = result.stdout.strip()
            if paths:
                logger.info("  LaunchServices registered paths for com.pushkavoice.app:")
                for p in paths.split("\n"):
                    logger.info("    %s", p)
            else:
                logger.info("  LaunchServices: no paths found for com.pushkavoice.app")
        except Exception as e:
            logger.warning("  LaunchServices check failed: %s", e)

    logger.info("  CRASH_LOG: %s", CRASH_LOG)
    logger.info("="*60)


def _ensure_single_instance():
    """Prevent multiple app instances using a lock file."""
    lock_path = DATA_DIR / ".pushkavoice.lock"
    import fcntl
    # Keep the file object alive for the process lifetime
    _ensure_single_instance._lock_file = open(lock_path, "w")
    try:
        fcntl.flock(_ensure_single_instance._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _ensure_single_instance._lock_file.write(str(os.getpid()))
        _ensure_single_instance._lock_file.flush()
        return True
    except (OSError, IOError):
        logger.warning("Another PushkaVoice instance is already running, exiting.")
        return False


def main():
    if not _ensure_single_instance():
        sys.exit(0)

    logger.info("PushkaVoice starting, PID=%d", os.getpid())
    _log_app_identity()

    # Load .env (check both DATA_DIR and APP_DIR for bundled mode)
    from dotenv import load_dotenv
    for env_dir in [DATA_DIR, APP_DIR]:
        env_path = env_dir / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            logger.info(f"Loaded .env from {env_dir}")
            break

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        logger.warning("HF_TOKEN not set. Longform transcription (>25s) will not work.")

    # Load config
    from utils.config import Config
    config = Config()
    config.save()

    # Create transcriber (model loading deferred until setup is complete)
    from core.transcriber import Transcriber
    transcriber = Transcriber()
    if config.get("setup_complete", False):
        transcriber.load_model_async()

    # Create API for pywebview
    from ui.window import Api
    api = Api(config, transcriber)

    # Create status bar icon
    from ui.statusbar import StatusBarIcon
    statusbar = StatusBarIcon()
    statusbar.setup()
    api.set_statusbar(statusbar)

    # After an app update the code signature changes, making old TCC entries
    # stale.  Detect build changes and automatically reset them.
    # Permission prompting is handled by the in-app wizard (ui/web/app.js).
    from utils.accessibility import (
        is_accessibility_granted, reset_all_permissions,
        is_input_monitoring_granted,
    )
    from utils.version import BUILD_NUMBER as _CURRENT_BUILD

    _stored_build = config.get("last_build_number", 0)
    if _CURRENT_BUILD != 0 and _stored_build != _CURRENT_BUILD:
        logger.info(
            "Build changed (%s → %s) — resetting all TCC entries",
            _stored_build, _CURRENT_BUILD,
        )
        reset_all_permissions()
        config.set("last_build_number", _CURRENT_BUILD)

    logger.info(
        "Permissions: accessibility=%s, input_monitoring=%s",
        is_accessibility_granted(), is_input_monitoring_granted(),
    )

    # Setup hotkey
    from ui.hotkey import HotkeyManager
    import queue

    event_queue = queue.Queue()

    def on_hotkey():
        event_queue.put("TOGGLE")

    # Start hotkey listener
    hotkey_mgr = HotkeyManager(config.hotkey, on_hotkey)
    hotkey_mgr.start()

    # Give Api a reference so UI-driven hotkey changes propagate
    api.set_hotkey_manager(hotkey_mgr)

    # Hotkey handler thread
    def hotkey_handler():
        while True:
            try:
                event = event_queue.get(timeout=0.5)
                if event == "TOGGLE":
                    # get_state() auto-transitions loading→idle
                    state = api.get_state()
                    if state == "idle":
                        api.start_recording()
                        logger.info("Recording started (hotkey)")
                    elif state == "recording":
                        # Run transcription in a thread so we don't block
                        threading.Thread(target=api.stop_recording, daemon=True).start()
                        logger.info("Recording stopped (hotkey)")
                    else:
                        logger.debug("Hotkey ignored, state=%s", state)
            except queue.Empty:
                continue

    hotkey_thread = threading.Thread(target=hotkey_handler, daemon=True)
    hotkey_thread.start()

    # Start pywebview
    import webview

    web_dir = str(APP_DIR / "ui" / "web")
    window = webview.create_window(
        "GigaAM Dictation",
        url=os.path.join(web_dir, "index.html"),
        js_api=api,
        width=440,
        height=680,
        resizable=True,
        min_size=(380, 500),
    )

    logger.info("Starting GigaAM Dictation app (pywebview)...")
    try:
        webview.start(debug=False)
    except Exception as e:
        logger.critical("pywebview.start() CRASHED: %s", e, exc_info=True)
        raise
    finally:
        logger.info("pywebview.start() returned. App shutting down.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        logger.info("SystemExit(%s)", e.code)
        raise
    except Exception as e:
        logger.critical("main() CRASHED: %s", e, exc_info=True)
        raise
