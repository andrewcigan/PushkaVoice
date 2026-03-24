import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from core.clipboard import copy_and_paste, copy_to_clipboard, remember_frontmost_app
from core.recorder import AudioRecorder
from core.text_cleaner import clean_text
from core.transcriber import Transcriber
from utils.accessibility import (
    is_accessibility_granted,
    is_input_monitoring_granted,
    open_accessibility_settings,
    open_input_monitoring_settings,
    prompt_accessibility,
    request_input_monitoring,
    reset_all_permissions,
)
from utils.config import Config
from utils.updater import Updater, check_for_update
from utils.version import VERSION, BUILD_NUMBER

logger = logging.getLogger(__name__)


class Api:
    """Python API exposed to JavaScript via pywebview."""

    def __init__(self, config: Config, transcriber: Transcriber):
        self.config = config
        self.transcriber = transcriber
        self._recorder = None
        self._state = "loading"  # loading, idle, recording, transcribing, error
        self._recording_start_time = None
        self._lock = threading.Lock()
        self._statusbar = None
        self._hotkey_mgr = None
        self._updater = Updater()
        self._accessibility_was_granted = False

    def set_statusbar(self, statusbar):
        self._statusbar = statusbar

    def set_hotkey_manager(self, hotkey_mgr):
        self._hotkey_mgr = hotkey_mgr

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        old = self._state
        self._state = value
        if old != value:
            logger.info(f"State: {old} -> {value}")
        if self._statusbar:
            self._statusbar.set_state(value)

    def get_state(self):
        # Auto-transition from loading to idle when model is ready
        if self._state == "loading" and self.transcriber.is_ready:
            self.state = "idle"
        # Detect model loading error (not loading, not ready, has error)
        if (self._state == "loading"
                and not self.transcriber.is_loading
                and not self.transcriber.is_ready
                and self.transcriber.has_error):
            return "load_error"
        # Report downloading sub-state
        if self._state == "loading" and self.transcriber.is_downloading:
            return "downloading"
        return self._state

    def get_loading_status(self):
        """Return model loading/download progress for the UI."""
        return self.transcriber.get_status()

    def get_devices(self):
        return AudioRecorder.list_devices()

    def get_config(self):
        return {
            "hotkey": self.config.hotkey,
            "microphone_device_id": self.config.microphone_device_id,
            "auto_paste": self.config.auto_paste,
            "sample_rate": self.config.sample_rate,
            "llm_cleanup": self.config.get("llm_cleanup", True),
            "llm_provider": self.config.get("llm_provider", "local"),
            "openrouter_api_key": self.config.get("openrouter_api_key", ""),
            "openrouter_model": self.config.get("openrouter_model", "google/gemma-3-4b-it:free"),
        }

    def set_config(self, key, value):
        self.config.set(key, value)
        if key == "hotkey":
            logger.info(f"Hotkey changed to: {value}")
            if self._hotkey_mgr:
                self._hotkey_mgr.update_hotkey(value)

    def is_setup_complete(self):
        """Check if initial setup has been completed."""
        return self.config.get("setup_complete", False)

    def complete_setup(self, provider):
        """Complete initial setup: save LLM provider choice and start model loading."""
        self.config.set("llm_provider", provider)
        self.config.set("setup_complete", True)
        # Start loading the transcriber model
        if not self.transcriber.is_ready and not self.transcriber.is_loading:
            self.transcriber.load_model_async()
        return {"ok": True}

    def reset_setup(self):
        """Reset setup so the choice screen shows again."""
        self.config.set("setup_complete", False)
        self.state = "loading"
        return {"ok": True}

    def retry_model_load(self):
        """Retry loading the model after an error."""
        self.state = "loading"
        self.transcriber.retry_load()
        return {"ok": True}

    def wait_for_model(self):
        """Non-blocking check if model is ready."""
        if self.transcriber.is_ready:
            self.state = "idle"
            return True
        return False

    def start_recording(self):
        with self._lock:
            if self._state not in ("idle", "error"):
                logger.warning(f"Cannot start recording in state: {self._state}")
                return {"error": f"Not ready (state={self._state})"}

            prev_state = self._state
            self.state = "recording"
            self._recording_start_time = time.time()
            # Remember which app has focus so auto-paste goes to the right place
            if self.config.auto_paste:
                remember_frontmost_app()
            logger.info(f"Starting recording (prev_state={prev_state}, device={self.config.microphone_device_id})")
            try:
                self._recorder = AudioRecorder(
                    device_id=self.config.microphone_device_id,
                    sample_rate=self.config.sample_rate,
                )
                self._recorder.start()
            except Exception as e:
                logger.error(f"Failed to start recorder: {e}", exc_info=True)
                self.state = "idle"
                return {"error": f"Microphone error: {e}"}
            logger.info("Recording started")
            return {"ok": True}

    def stop_recording(self):
        with self._lock:
            if self._state != "recording":
                logger.warning(f"stop_recording called but state={self._state}")
                return {"error": "Not recording"}

            self.state = "transcribing"
            logger.info("State -> transcribing")

        duration = time.time() - self._recording_start_time
        logger.info(f"Recording stopped. Duration: {duration:.1f}s")

        # Always save WAV regardless of transcription result
        wav_path = self._recorder.stop(save_dir=self.config.dictations_folder)
        self._recorder = None

        if not wav_path:
            logger.warning("No audio captured (empty wav_path)")
            self.state = "idle"
            return {"error": "No audio captured"}

        return self._transcribe_file(wav_path, duration)

    def _transcribe_file(self, wav_path, duration=0):
        """Transcribe a WAV file. Used by both stop_recording and retry."""
        try:
            start = time.time()
            logger.info(f"Starting transcription: {wav_path}")
            text = self.transcriber.transcribe(wav_path)
            elapsed = time.time() - start
            logger.info(f"Transcribed in {elapsed:.1f}s: {text[:80]}...")

            if not text.strip():
                # Save error marker but keep WAV
                err_path = wav_path.replace(".wav", ".error.txt")
                with open(err_path, "w", encoding="utf-8") as f:
                    f.write("No speech detected")
                self.state = "idle"
                logger.info("No speech detected, returning to idle")
                return {"error": "No speech detected", "wav_path": wav_path}

            # Clean text with LLM if available
            raw_text = text
            if self.config.get("llm_cleanup", True):
                provider = self.config.get("llm_provider", "local")
                logger.info(f"Cleaning text with LLM (provider: {provider})...")
                try:
                    text = clean_text(text, self.config)
                    if text != raw_text:
                        logger.info(f"LLM cleaned: '{raw_text[:50]}' -> '{text[:50]}'")
                except Exception as e:
                    logger.warning(f"LLM cleanup failed, using raw text: {e}")
                    text = raw_text

            # Save text file (cleaned version)
            txt_path = wav_path.replace(".wav", ".txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(text)

            # Save raw ASR output
            raw_path = wav_path.replace(".wav", ".raw.txt")
            with open(raw_path, "w", encoding="utf-8") as f:
                f.write(raw_text)

            # Remove error marker if retry succeeded
            err_path = wav_path.replace(".wav", ".error.txt")
            if os.path.exists(err_path):
                os.remove(err_path)

            # Copy and paste
            try:
                if self.config.auto_paste:
                    copy_and_paste(text)
                else:
                    copy_to_clipboard(text)
                logger.info("Text copied to clipboard")
            except Exception as e:
                logger.warning(f"Clipboard operation failed: {e}")

            self.state = "idle"
            logger.info("Transcription complete, returning to idle")
            return {"text": text, "raw_text": raw_text, "duration": duration, "elapsed": elapsed}

        except Exception as e:
            logger.error(f"Transcription error: {e}", exc_info=True)
            # Save error info but keep WAV
            try:
                err_path = wav_path.replace(".wav", ".error.txt")
                with open(err_path, "w", encoding="utf-8") as f:
                    f.write(str(e))
            except Exception:
                pass
            # Always return to idle so the user can try again
            self.state = "idle"
            logger.info("Transcription failed, returning to idle")
            return {"error": str(e), "wav_path": wav_path}

    def retry_transcription(self, wav_path):
        """Retry transcription for a failed recording."""
        if not os.path.exists(wav_path):
            return {"error": "WAV file not found"}

        self.state = "transcribing"
        return self._transcribe_file(wav_path)

    def get_history(self):
        folder = self.config.dictations_folder
        items = []

        # Get all WAV files (every recording)
        wav_files = sorted(Path(folder).glob("*.wav"), reverse=True)

        for wav in wav_files[:30]:  # last 30
            try:
                name = wav.stem
                parts = name.split("_")
                if len(parts) >= 2:
                    time_part = parts[1].replace("-", ":")
                    display_time = time_part[:5]  # HH:MM
                else:
                    display_time = name

                txt_file = wav.with_suffix(".txt")
                err_file = wav.parent / (wav.stem + ".error.txt")

                if txt_file.exists():
                    # Successfully transcribed
                    text = txt_file.read_text(encoding="utf-8").strip()
                    items.append({
                        "time": display_time,
                        "text": text,
                        "file": str(txt_file),
                        "wav": str(wav),
                        "status": "ok",
                    })
                elif err_file.exists():
                    # Failed transcription
                    error = err_file.read_text(encoding="utf-8").strip()
                    items.append({
                        "time": display_time,
                        "text": f"[Error: {error}]",
                        "file": str(err_file),
                        "wav": str(wav),
                        "status": "error",
                    })
                else:
                    # WAV exists but no txt/error — not yet transcribed
                    items.append({
                        "time": display_time,
                        "text": "[Not transcribed]",
                        "file": "",
                        "wav": str(wav),
                        "status": "pending",
                    })
            except Exception:
                continue

        return items

    def copy_text(self, text):
        copy_to_clipboard(text)
        return {"ok": True}

    def open_dictations_folder(self):
        folder = self.config.dictations_folder
        subprocess.run(["open", folder], check=False)
        return {"ok": True}

    def get_log_path(self):
        """Return the path to the log file."""
        if getattr(sys, 'frozen', False):
            log_dir = Path.home() / ".pushkavoice"
        else:
            log_dir = Path(__file__).parent.parent
        return str(log_dir / "dictation.log")

    def get_logs(self, max_lines=200):
        """Return last N lines of the log file."""
        log_path = self.get_log_path()
        try:
            if not os.path.exists(log_path):
                return {"lines": [], "path": log_path}
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
            return {
                "lines": all_lines[-max_lines:],
                "path": log_path,
            }
        except Exception as e:
            return {"lines": [f"Error reading logs: {e}"], "path": log_path}

    def open_log_file(self):
        """Open log file in Finder / default text editor."""
        log_path = self.get_log_path()
        if os.path.exists(log_path):
            subprocess.run(["open", log_path], check=False)
        return {"ok": True, "path": log_path}

    def check_accessibility(self):
        """Check both Accessibility and Input Monitoring permissions.

        Also restarts the hotkey listener once when Input Monitoring is newly detected.
        Returns granted (both permissions ok) and hotkey_active (CGEventTap alive).
        """
        ax_granted = is_accessibility_granted()
        im_granted = is_input_monitoring_granted()
        granted = ax_granted and im_granted
        logger.debug(f"Permission check: accessibility={ax_granted}, input_monitoring={im_granted}")

        if im_granted and not self._accessibility_was_granted and self._hotkey_mgr:
            # Input Monitoring newly granted — restart hotkey listener
            self._accessibility_was_granted = True
            logger.info("Input Monitoring newly granted — restarting hotkey listener")
            self._hotkey_mgr.restart()
        elif not im_granted:
            self._accessibility_was_granted = False

        hotkey_active = bool(self._hotkey_mgr and self._hotkey_mgr.is_tap_active)
        return {
            "granted": granted,
            "accessibility": ax_granted,
            "input_monitoring": im_granted,
            "hotkey_active": hotkey_active,
        }

    def request_accessibility(self):
        """Prompt user for both Accessibility and Input Monitoring permissions."""
        logger.info("Requesting permissions...")
        ax = prompt_accessibility()
        im = request_input_monitoring()
        logger.info(f"Permission prompt results: accessibility={ax}, input_monitoring={im}")
        if im and self._hotkey_mgr:
            self._hotkey_mgr.restart()
        return {"granted": ax and im, "accessibility": ax, "input_monitoring": im}

    def restart_hotkey(self):
        """Manually restart the hotkey listener (e.g. after granting permissions)."""
        if self._hotkey_mgr:
            self._hotkey_mgr.restart()
            logger.info("Hotkey listener restarted manually")
        return {"ok": True}

    def reset_and_request_accessibility(self):
        """Reset stale TCC entries, then re-prompt for both permissions.

        Each ad-hoc signed build gets a new code signature, making old
        TCC entries invalid.  This clears them and re-prompts.
        """
        logger.info("Resetting all TCC entries...")
        reset_ok = reset_all_permissions()
        logger.info(f"TCC reset result: {reset_ok}")
        # Now re-prompt — this will add fresh entries for the current binary
        ax = prompt_accessibility()
        im = request_input_monitoring()
        logger.info(f"Re-prompt results: accessibility={ax}, input_monitoring={im}")
        if im and self._hotkey_mgr:
            self._hotkey_mgr.restart()
        return {"reset_ok": reset_ok, "granted": ax and im}

    def open_accessibility_settings(self):
        """Open System Settings → Accessibility pane."""
        open_accessibility_settings()
        return {"ok": True}

    def open_permission_settings(self, perm_type: str):
        """Open System Settings to the correct Privacy pane."""
        if perm_type == "accessibility":
            open_accessibility_settings()
        elif perm_type == "input_monitoring":
            open_input_monitoring_settings()
        return {"ok": True}

    def prompt_single_permission(self, perm_type: str):
        """Trigger macOS system prompt for one permission at a time."""
        granted = False
        if perm_type == "accessibility":
            granted = prompt_accessibility()
        elif perm_type == "input_monitoring":
            granted = request_input_monitoring()
            if granted and self._hotkey_mgr:
                self._hotkey_mgr.restart()
        logger.info(f"prompt_single_permission({perm_type}) = {granted}")
        return {"granted": granted}

    # ── Updates ──────────────────────────────────────────────────

    def get_version(self):
        """Return current app version info."""
        return {"version": VERSION, "build": BUILD_NUMBER}

    def check_for_update(self):
        """Check GitHub Releases for a newer version."""
        return check_for_update()

    def start_update(self, download_url):
        """Start downloading and installing an update in the background."""
        if self._updater._downloading:
            return {"error": "Update already in progress"}
        threading.Thread(
            target=self._updater.download_and_install,
            args=(download_url,),
            daemon=True,
        ).start()
        return {"ok": True}

    def get_update_status(self):
        """Return current update download/install progress."""
        return self._updater.status

    def restart_app(self):
        """Restart the application after an update."""
        Updater.restart_app()
        return {"ok": True}
