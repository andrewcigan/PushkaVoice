import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from core.clipboard import copy_and_paste, copy_to_clipboard
from core.recorder import AudioRecorder
from core.text_cleaner import clean_text
from core.transcriber import Transcriber
from utils.config import Config

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

    def set_statusbar(self, statusbar):
        self._statusbar = statusbar

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        self._state = value
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
            "llm_provider": self.config.get("llm_provider", "local"),
            "openrouter_api_key": self.config.get("openrouter_api_key", ""),
            "openrouter_model": self.config.get("openrouter_model", "google/gemma-3-4b-it:free"),
        }

    def set_config(self, key, value):
        self.config.set(key, value)
        if key == "hotkey":
            logger.info(f"Hotkey changed to: {value}")

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
                return {"error": "Not ready"}

            self.state = "recording"
            self._recording_start_time = time.time()
            self._recorder = AudioRecorder(
                device_id=self.config.microphone_device_id,
                sample_rate=self.config.sample_rate,
            )
            self._recorder.start()
            logger.info("Recording started (from UI)")
            return {"ok": True}

    def stop_recording(self):
        with self._lock:
            if self._state != "recording":
                return {"error": "Not recording"}

            self.state = "transcribing"

        duration = time.time() - self._recording_start_time
        logger.info(f"Recording stopped. Duration: {duration:.1f}s")

        # Always save WAV regardless of transcription result
        wav_path = self._recorder.stop(save_dir=self.config.dictations_folder)
        self._recorder = None

        if not wav_path:
            self.state = "error"
            return {"error": "No audio captured"}

        return self._transcribe_file(wav_path, duration)

    def _transcribe_file(self, wav_path, duration=0):
        """Transcribe a WAV file. Used by both stop_recording and retry."""
        try:
            start = time.time()
            text = self.transcriber.transcribe(wav_path)
            elapsed = time.time() - start
            logger.info(f"Transcribed in {elapsed:.1f}s: {text[:80]}...")

            if not text.strip():
                # Save error marker but keep WAV
                err_path = wav_path.replace(".wav", ".error.txt")
                with open(err_path, "w", encoding="utf-8") as f:
                    f.write("No speech detected")
                self.state = "idle"
                return {"error": "No speech detected", "wav_path": wav_path}

            # Clean text with LLM if available
            raw_text = text
            if self.config.get("llm_cleanup", True):
                provider = self.config.get("llm_provider", "local")
                logger.info(f"Cleaning text with LLM (provider: {provider})...")
                text = clean_text(text, self.config)
                if text != raw_text:
                    logger.info(f"LLM cleaned: '{raw_text[:50]}' -> '{text[:50]}'")


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
            if self.config.auto_paste:
                copy_and_paste(text)
            else:
                copy_to_clipboard(text)

            self.state = "idle"
            return {"text": text, "raw_text": raw_text, "duration": duration, "elapsed": elapsed}

        except Exception as e:
            logger.error(f"Transcription error: {e}")
            # Save error info but keep WAV
            err_path = wav_path.replace(".wav", ".error.txt")
            with open(err_path, "w", encoding="utf-8") as f:
                f.write(str(e))
            self.state = "error"
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
