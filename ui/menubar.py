import logging
import os
import queue
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import rumps

from core.clipboard import copy_and_paste, copy_to_clipboard
from core.recorder import AudioRecorder
from core.transcriber import Transcriber
from ui.hotkey import HotkeyManager
from ui.indicator import FloatingIndicator
from utils.config import Config

logger = logging.getLogger(__name__)

# States
IDLE = "idle"
RECORDING = "recording"
TRANSCRIBING = "transcribing"
LOADING = "loading"


class DictationApp(rumps.App):
    def __init__(self, config: Config):
        super().__init__("Dictation", title="\U0001F3A4")  # microphone emoji as title
        self.config = config
        self._state = LOADING
        self._event_queue = queue.Queue()
        self._recorder = None
        self._transcriber = Transcriber()
        self._indicator = FloatingIndicator()
        self._hotkey_manager = None
        self._recording_start_time = None

        # Menu items
        self._status_item = rumps.MenuItem("Loading model...")
        self._toggle_item = rumps.MenuItem("Start Dictation", callback=self._on_toggle_click)
        self._toggle_item.set_callback(None)  # disabled until model loads

        # Microphone submenu
        self._mic_menu = rumps.MenuItem("Microphone")

        # Hotkey display
        self._hotkey_display = rumps.MenuItem(f"Hotkey: {self.config.hotkey}")

        # Auto-paste toggle
        self._autopaste_item = rumps.MenuItem(
            "Auto-paste", callback=self._toggle_autopaste
        )
        self._autopaste_item.state = self.config.auto_paste

        # Open dictations folder
        self._open_folder_item = rumps.MenuItem(
            "Open Dictations Folder", callback=self._open_dictations_folder
        )

        # Autostart
        from utils.autostart import is_installed
        self._autostart_item = rumps.MenuItem(
            "Start on Login", callback=self._toggle_autostart
        )
        self._autostart_item.state = is_installed()

        self.menu = [
            self._status_item,
            None,  # separator
            self._toggle_item,
            None,
            self._mic_menu,
            self._hotkey_display,
            self._autopaste_item,
            None,
            self._open_folder_item,
            self._autostart_item,
        ]

        # Build mic menu after self.menu is set (rumps needs it)
        self._build_mic_menu()

        # Start polling timer
        self._poll_timer = rumps.Timer(self._poll_events, 0.2)
        self._poll_timer.start()

        # Start model loading
        self._transcriber.load_model_async()
        self._model_check_timer = rumps.Timer(self._check_model_loaded, 1.0)
        self._model_check_timer.start()

    def _build_mic_menu(self):
        devices = AudioRecorder.list_devices()

        # Remove existing items if any
        try:
            if hasattr(self._mic_menu, '_menu') and self._mic_menu._menu is not None:
                self._mic_menu.clear()
        except Exception:
            pass

        default_item = rumps.MenuItem("System Default", callback=self._select_mic)
        default_item.representedObject = None
        if self.config.microphone_device_id is None:
            default_item.state = True
        self._mic_menu[default_item.title] = default_item

        for dev in devices:
            item = rumps.MenuItem(dev["name"], callback=self._select_mic)
            item.representedObject = dev["id"]
            if self.config.microphone_device_id == dev["id"]:
                item.state = True
            self._mic_menu[item.title] = item

    def _select_mic(self, sender):
        # Uncheck all
        for item in self._mic_menu.values():
            if isinstance(item, rumps.MenuItem):
                item.state = False
        sender.state = True
        self.config.set("microphone_device_id", sender.representedObject)

    def _check_model_loaded(self, _):
        if self._transcriber.is_ready:
            self._state = IDLE
            self._status_item.title = "Ready"
            self.title = "\U0001F3A4"
            self._toggle_item.set_callback(self._on_toggle_click)
            self._model_check_timer.stop()

            # Start hotkey listener
            self._hotkey_manager = HotkeyManager(
                self.config.hotkey,
                lambda: self._event_queue.put(("TOGGLE",)),
            )
            self._hotkey_manager.start()

            logger.info("App ready")
        elif not self._transcriber.is_loading:
            # Loading failed
            self._status_item.title = "Model load failed!"
            self._model_check_timer.stop()

    def _poll_events(self, _):
        while not self._event_queue.empty():
            try:
                event = self._event_queue.get_nowait()
            except queue.Empty:
                break

            if event[0] == "TOGGLE":
                self._handle_toggle()
            elif event[0] == "DONE":
                self._on_transcription_done(event[1], event[2])
            elif event[0] == "ERROR":
                self._on_error(event[1])

    def _on_toggle_click(self, _):
        self._handle_toggle()

    def _handle_toggle(self):
        if self._state == IDLE:
            self._start_recording()
        elif self._state == RECORDING:
            self._stop_recording()

    def _start_recording(self):
        self._state = RECORDING
        self.title = "\U0001F534"  # red circle
        self._status_item.title = "Recording..."
        self._toggle_item.title = "Stop Dictation"
        self._indicator.show("red")
        self._recording_start_time = time.time()

        self._recorder = AudioRecorder(
            device_id=self.config.microphone_device_id,
            sample_rate=self.config.sample_rate,
        )
        self._recorder.start()
        logger.info("Recording started")

    def _stop_recording(self):
        self._state = TRANSCRIBING
        self.title = "\U0001F7E1"  # yellow circle
        self._status_item.title = "Transcribing..."
        self._toggle_item.title = "Processing..."
        self._toggle_item.set_callback(None)
        self._indicator.show("yellow")

        duration = time.time() - self._recording_start_time
        logger.info(f"Recording stopped. Duration: {duration:.1f}s")

        # Stop recording and save WAV
        wav_path = self._recorder.stop(save_dir=self.config.dictations_folder)
        self._recorder = None

        if not wav_path:
            self._reset_to_idle()
            return

        # Start transcription in background
        t = threading.Thread(
            target=self._transcribe_worker, args=(wav_path,), daemon=True
        )
        t.start()

    def _transcribe_worker(self, wav_path):
        try:
            start = time.time()
            text = self._transcriber.transcribe(wav_path)
            elapsed = time.time() - start
            logger.info(f"Transcription done in {elapsed:.1f}s: {text[:80]}...")
            self._event_queue.put(("DONE", text, wav_path))
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            self._event_queue.put(("ERROR", str(e)))

    def _on_transcription_done(self, text, wav_path):
        if not text.strip():
            rumps.notification(
                "Dictation", "No speech detected", "Try speaking louder or closer to the microphone"
            )
            self._reset_to_idle()
            return

        # Save text alongside WAV
        txt_path = wav_path.replace(".wav", ".txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
        logger.info(f"Saved: {txt_path}")

        # Copy and paste
        if self.config.auto_paste:
            copy_and_paste(text)
        else:
            copy_to_clipboard(text)

        # Notification
        preview = text[:60] + "..." if len(text) > 60 else text
        rumps.notification("Dictation", "Text ready", preview)

        self._reset_to_idle()

    def _on_error(self, error_msg):
        rumps.notification("Dictation Error", "", error_msg)
        self._reset_to_idle()

    def _reset_to_idle(self):
        self._state = IDLE
        self.title = "\U0001F3A4"
        self._status_item.title = "Ready"
        self._toggle_item.title = "Start Dictation"
        self._toggle_item.set_callback(self._on_toggle_click)
        self._indicator.hide()

    def _toggle_autopaste(self, sender):
        sender.state = not sender.state
        self.config.set("auto_paste", bool(sender.state))

    def _open_dictations_folder(self, _):
        folder = self.config.dictations_folder
        subprocess.run(["open", folder], check=False)

    def _toggle_autostart(self, sender):
        from utils.autostart import install, uninstall, is_installed

        if is_installed():
            uninstall()
            sender.state = False
        else:
            install()
            sender.state = True
