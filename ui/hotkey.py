import threading
import logging
from pynput import keyboard

logger = logging.getLogger(__name__)


class HotkeyManager:
    def __init__(self, hotkey_string: str, callback):
        self._hotkey_string = hotkey_string
        self._callback = callback
        self._listener = None

    def start(self):
        try:
            self._listener = keyboard.GlobalHotKeys({
                self._hotkey_string: self._callback,
            })
            self._listener.daemon = True
            self._listener.start()
            logger.info(f"Hotkey listener started: {self._hotkey_string}")
        except Exception as e:
            logger.error(f"Failed to start hotkey listener: {e}")

    def stop(self):
        if self._listener:
            self._listener.stop()
            self._listener = None

    def update_hotkey(self, new_hotkey_string: str):
        self.stop()
        self._hotkey_string = new_hotkey_string
        self.start()
