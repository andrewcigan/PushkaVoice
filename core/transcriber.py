import os
import threading
import logging
import time
from pathlib import Path

from utils.audio_utils import get_wav_duration

logger = logging.getLogger(__name__)

LONGFORM_THRESHOLD = 25.0  # seconds
GIGAAM_CACHE_DIR = Path.home() / ".cache" / "gigaam"
# Approximate model file sizes for progress tracking (bytes)
MODEL_EXPECTED_SIZES = {
    "v3_e2e_rnnt.ckpt": 500_000_000,  # ~500 MB
    "v3_e2e_rnnt_tokenizer.model": 1_000_000,  # ~1 MB
}


class Transcriber:
    def __init__(self):
        self._model = None
        self._loading = False
        self._ready_event = threading.Event()
        self._status = "Waiting..."
        self._download_progress = 0  # 0-100
        self._is_downloading = False

    def _check_model_cached(self) -> bool:
        """Check if model files already exist in cache."""
        ckpt = GIGAAM_CACHE_DIR / "v3_e2e_rnnt.ckpt"
        return ckpt.exists() and ckpt.stat().st_size > 100_000_000

    def _monitor_download(self):
        """Monitor download progress by checking cache file sizes."""
        self._is_downloading = True
        self._status = "Downloading GigaAM model..."
        self._download_progress = 0

        total_expected = sum(MODEL_EXPECTED_SIZES.values())

        while self._is_downloading and self._loading:
            total_downloaded = 0
            for filename, expected in MODEL_EXPECTED_SIZES.items():
                fpath = GIGAAM_CACHE_DIR / filename
                if fpath.exists():
                    total_downloaded += min(fpath.stat().st_size, expected)

            if total_expected > 0:
                self._download_progress = min(99, int(total_downloaded * 100 / total_expected))
                mb_done = total_downloaded / (1024 * 1024)
                mb_total = total_expected / (1024 * 1024)
                self._status = f"Downloading model... {mb_done:.0f} / {mb_total:.0f} MB"

            time.sleep(0.5)

        self._is_downloading = False

    def load_model(self):
        if self._model is not None or self._loading:
            return
        self._loading = True

        # Start download monitor if model not cached
        monitor_thread = None
        if not self._check_model_cached():
            self._status = "Downloading GigaAM model..."
            self._is_downloading = True
            monitor_thread = threading.Thread(target=self._monitor_download, daemon=True)
            monitor_thread.start()
        else:
            self._status = "Loading model..."

        try:
            import gigaam
            logger.info("Loading GigaAM v3_e2e_rnnt model...")
            self._status = "Loading model..." if self._check_model_cached() else self._status
            self._model = gigaam.load_model("v3_e2e_rnnt")
            self._status = "Ready"
            logger.info("Model loaded successfully")
        except Exception as e:
            self._status = f"Error: {e}"
            logger.error(f"Failed to load model: {e}")
        finally:
            self._is_downloading = False
            self._loading = False
            self._ready_event.set()
            if monitor_thread:
                monitor_thread.join(timeout=2)

    def load_model_async(self):
        t = threading.Thread(target=self.load_model, daemon=True)
        t.start()

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    @property
    def is_loading(self) -> bool:
        return self._loading

    @property
    def is_downloading(self) -> bool:
        return self._is_downloading

    def get_status(self) -> dict:
        """Return current loading status for the UI."""
        return {
            "message": self._status,
            "progress": self._download_progress,
            "downloading": self._is_downloading,
            "loading": self._loading,
            "ready": self.is_ready,
        }

    def wait_until_ready(self, timeout=None) -> bool:
        self._ready_event.wait(timeout=timeout)
        return self.is_ready

    def transcribe(self, audio_path: str) -> str:
        if not self.is_ready:
            raise RuntimeError("Model not loaded yet")

        duration = get_wav_duration(audio_path)
        logger.info(f"Audio duration: {duration:.1f}s")

        if duration > LONGFORM_THRESHOLD:
            logger.info("Using transcribe_longform...")
            result = self._model.transcribe_longform(audio_path)
            if isinstance(result, list):
                # transcribe_longform returns list of segments
                texts = []
                for segment in result:
                    if isinstance(segment, dict):
                        texts.append(segment.get("transcription", segment.get("text", "")))
                    elif isinstance(segment, (list, tuple)):
                        texts.append(str(segment[-1]) if segment else "")
                    else:
                        texts.append(str(segment))
                return " ".join(texts)
            return str(result)
        else:
            logger.info("Using transcribe...")
            result = self._model.transcribe(audio_path)
            if isinstance(result, list):
                return " ".join(str(r) for r in result)
            return str(result)
