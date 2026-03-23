import os
import threading
import logging
import time
from pathlib import Path

from utils.audio_utils import get_wav_duration

logger = logging.getLogger(__name__)

LONGFORM_THRESHOLD = 25.0  # seconds

# All possible cache locations where gigaam/torch/huggingface may download
CACHE_DIRS = [
    Path.home() / ".cache" / "gigaam",
    Path.home() / ".cache" / "torch" / "hub" / "checkpoints",
    Path.home() / ".cache" / "huggingface" / "hub",
    Path.home() / ".cache" / "huggingface",
]

# Known model file patterns and expected total size (~500 MB)
MODEL_PATTERNS = ["*rnnt*", "*gigaam*", "*e2e*", "*.ckpt", "*.bin", "*.safetensors"]
MODEL_EXPECTED_TOTAL = 500_000_000  # ~500 MB


def _scan_download_bytes() -> int:
    """Scan all known cache directories for model-related files and return total bytes."""
    seen = set()
    total = 0
    for cache_dir in CACHE_DIRS:
        if not cache_dir.exists():
            continue
        try:
            all_patterns = MODEL_PATTERNS + ["*.incomplete"]
            for pattern in all_patterns:
                for f in cache_dir.rglob(pattern):
                    if f.is_file() and f not in seen:
                        seen.add(f)
                        try:
                            total += f.stat().st_size
                        except OSError:
                            pass
        except OSError:
            pass
    return total


class Transcriber:
    def __init__(self):
        self._model = None
        self._loading = False
        self._ready_event = threading.Event()
        self._status = "Waiting..."
        self._download_progress = 0  # 0-100
        self._is_downloading = False
        self._download_speed = 0.0  # bytes/sec
        self._download_eta = 0  # seconds remaining
        self._downloaded_mb = 0.0
        self._total_mb = MODEL_EXPECTED_TOTAL / (1024 * 1024)
        self._download_start_time = 0.0
        self._load_start_time = 0.0
        self._elapsed_seconds = 0
        self._speed_samples = []  # list of (time, bytes) for rolling speed

    def _check_model_cached(self) -> bool:
        """Check if model files already exist in cache (fully downloaded)."""
        ckpt = Path.home() / ".cache" / "gigaam" / "v3_e2e_rnnt.ckpt"
        # Must be close to expected size (within 10%) to be considered complete
        if ckpt.exists():
            size = ckpt.stat().st_size
            return size > MODEL_EXPECTED_TOTAL * 0.9
        return False

    def _monitor_download(self):
        """Monitor download progress by scanning cache directories for model files."""
        self._is_downloading = True
        self._status = "Downloading model..."
        self._download_progress = 0
        self._download_start_time = time.time()
        self._speed_samples = []

        # Take initial snapshot to detect new bytes
        initial_bytes = _scan_download_bytes()

        while self._is_downloading and self._loading:
            now = time.time()
            current_bytes = _scan_download_bytes()
            new_bytes = max(0, current_bytes - initial_bytes)

            self._downloaded_mb = new_bytes / (1024 * 1024)
            self._elapsed_seconds = int(now - self._download_start_time)

            if MODEL_EXPECTED_TOTAL > 0:
                self._download_progress = min(99, int(new_bytes * 100 / MODEL_EXPECTED_TOTAL))

            # Track speed with rolling window (last 10 samples = 5 seconds)
            self._speed_samples.append((now, new_bytes))
            if len(self._speed_samples) > 10:
                self._speed_samples = self._speed_samples[-10:]

            # Calculate speed from rolling window
            if len(self._speed_samples) >= 2:
                t0, b0 = self._speed_samples[0]
                t1, b1 = self._speed_samples[-1]
                dt = t1 - t0
                if dt > 0.5:
                    self._download_speed = (b1 - b0) / dt
                    remaining = MODEL_EXPECTED_TOTAL - new_bytes
                    if self._download_speed > 0:
                        self._download_eta = int(remaining / self._download_speed)
                    else:
                        self._download_eta = 0

            # Build status message
            speed_mbs = self._download_speed / (1024 * 1024)
            if new_bytes > 0 and self._download_progress > 0:
                self._status = (
                    f"Downloading model... {self._downloaded_mb:.0f} / {self._total_mb:.0f} MB"
                )
            else:
                self._status = "Downloading model... waiting for data"

            time.sleep(0.5)

        self._is_downloading = False

    def load_model(self):
        if self._model is not None or self._loading:
            return
        self._loading = True
        self._load_start_time = time.time()

        # Start download monitor — always, even if cached
        # (it will detect if actual downloading happens)
        monitor_thread = None
        if not self._check_model_cached():
            self._status = "Downloading model..."
            self._is_downloading = True
            monitor_thread = threading.Thread(target=self._monitor_download, daemon=True)
            monitor_thread.start()
        else:
            self._status = "Loading model into memory..."

        try:
            import gigaam
            logger.info("Loading GigaAM v3_e2e_rnnt model...")
            if self._check_model_cached():
                self._status = "Loading model into memory..."
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
        speed_mbs = self._download_speed / (1024 * 1024) if self._download_speed else 0.0

        # Always track elapsed time while loading
        if self._loading and self._load_start_time > 0:
            self._elapsed_seconds = int(time.time() - self._load_start_time)

        return {
            "message": self._status,
            "progress": self._download_progress,
            "downloading": self._is_downloading,
            "loading": self._loading,
            "ready": self.is_ready,
            "speed_mbs": round(speed_mbs, 1),
            "eta_seconds": self._download_eta,
            "downloaded_mb": round(self._downloaded_mb, 1),
            "total_mb": round(self._total_mb, 1),
            "elapsed_seconds": self._elapsed_seconds,
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
