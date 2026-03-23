#!/usr/bin/env python3
import logging
import os
import sys
import threading
import time
from pathlib import Path

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

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(DATA_DIR / "dictation.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def main():
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

    # Setup hotkey
    from ui.hotkey import HotkeyManager
    import queue

    event_queue = queue.Queue()

    def on_hotkey():
        event_queue.put("TOGGLE")

    # Start hotkey listener
    hotkey_mgr = HotkeyManager(config.hotkey, on_hotkey)
    hotkey_mgr.start()

    # Hotkey handler thread
    def hotkey_handler():
        while True:
            try:
                event = event_queue.get(timeout=0.5)
                if event == "TOGGLE":
                    if api.state == "idle":
                        api.start_recording()
                        logger.info("Recording started (hotkey)")
                    elif api.state == "recording":
                        # Run transcription in a thread so we don't block
                        threading.Thread(target=api.stop_recording, daemon=True).start()
                        logger.info("Recording stopped (hotkey)")
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

    logger.info("Starting GigaAM Dictation app...")
    webview.start(debug=False)


if __name__ == "__main__":
    main()
