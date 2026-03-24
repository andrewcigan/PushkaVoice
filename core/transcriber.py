import os
import threading
import logging
import time
import zipfile
from pathlib import Path

from utils.audio_utils import get_wav_duration

logger = logging.getLogger(__name__)

LONGFORM_THRESHOLD = 25.0  # seconds

# Model name used by gigaam library
MODEL_NAME = "rnnt"

# All possible cache locations where gigaam/torch/huggingface may download
GIGAAM_CACHE_DIR = Path.home() / ".cache" / "gigaam"
CACHE_DIRS = [
    GIGAAM_CACHE_DIR,
    Path.home() / ".cache" / "torch" / "hub" / "checkpoints",
    Path.home() / ".cache" / "huggingface" / "hub",
    Path.home() / ".cache" / "huggingface",
]

# Known model file patterns and expected total size (~500 MB)
MODEL_PATTERNS = ["*rnnt*", "*gigaam*", "*.ckpt", "*.bin", "*.safetensors"]
MODEL_EXPECTED_TOTAL = 500_000_000  # ~500 MB

# Minimum valid model file size (50 MB)
MODEL_MIN_SIZE = 50_000_000


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


def _is_valid_checkpoint(path: Path) -> bool:
    """Check if a .ckpt file is a valid PyTorch checkpoint (zip archive)."""
    try:
        if not path.is_file():
            return False
        if path.stat().st_size < MODEL_MIN_SIZE:
            return False
        # PyTorch checkpoints are zip files — verify the archive is readable
        with zipfile.ZipFile(path, 'r') as zf:
            zf.testzip()
        return True
    except (zipfile.BadZipFile, OSError, Exception):
        return False


def _find_cached_model() -> bool:
    """Check if a valid model checkpoint exists in the gigaam cache directory."""
    if not GIGAAM_CACHE_DIR.exists():
        return False
    try:
        for f in GIGAAM_CACHE_DIR.glob("*.ckpt"):
            if _is_valid_checkpoint(f):
                return True
    except OSError:
        pass
    return False


def _cleanup_corrupted_cache():
    """Remove corrupted .ckpt files from the gigaam cache directory."""
    if not GIGAAM_CACHE_DIR.exists():
        return
    try:
        for f in GIGAAM_CACHE_DIR.glob("*.ckpt"):
            if f.is_file() and not _is_valid_checkpoint(f):
                size_mb = f.stat().st_size / (1024 * 1024)
                logger.warning(f"Removing corrupted cache file: {f} ({size_mb:.1f} MB)")
                f.unlink()
    except OSError as e:
        logger.warning(f"Failed to clean up cache: {e}")


class Transcriber:
    def __init__(self):
        self._model = None
        self._loading = False
        self._ready_event = threading.Event()
        self._status = "Waiting..."
        self._error = None  # error message if loading failed
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

    def _monitor_download(self):
        """Monitor download progress by scanning cache directories for model files."""
        self._is_downloading = True
        self._status = "Downloading model..."
        self._download_progress = 0
        self._download_start_time = time.time()
        self._speed_samples = []

        initial_bytes = _scan_download_bytes()

        while self._is_downloading and self._loading:
            now = time.time()
            current_bytes = _scan_download_bytes()
            new_bytes = max(0, current_bytes - initial_bytes)

            self._downloaded_mb = new_bytes / (1024 * 1024)
            self._elapsed_seconds = int(now - self._download_start_time)

            if MODEL_EXPECTED_TOTAL > 0:
                self._download_progress = min(99, int(new_bytes * 100 / MODEL_EXPECTED_TOTAL))

            self._speed_samples.append((now, new_bytes))
            if len(self._speed_samples) > 10:
                self._speed_samples = self._speed_samples[-10:]

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
        self._error = None
        self._load_start_time = time.time()

        # Clean up any corrupted cache files from previous failed downloads
        _cleanup_corrupted_cache()

        monitor_thread = None
        model_cached = _find_cached_model()
        if not model_cached:
            self._status = "Downloading model..."
            self._is_downloading = True
            monitor_thread = threading.Thread(target=self._monitor_download, daemon=True)
            monitor_thread.start()
        else:
            self._status = "Loading model into memory..."

        try:
            # Patch subprocess.run BEFORE loading gigaam so ffmpeg calls
            # are intercepted from the very first import
            from core.audio_compat import patch_gigaam
            patch_gigaam()

            import gigaam
            logger.info(f"Loading GigaAM '{MODEL_NAME}' model...")
            if model_cached:
                self._status = "Loading model into memory..."
            self._model = gigaam.load_model(MODEL_NAME)

            self._status = "Ready"
            self._error = None
            logger.info("Model loaded successfully")
        except RuntimeError as e:
            if "PytorchStreamReader" in str(e) or "zip archive" in str(e):
                logger.warning("Corrupted model file detected, cleaning cache and retrying...")
                _cleanup_corrupted_cache()
                self._error = "Corrupted model cache removed. Please retry to re-download."
                self._status = f"Error: {self._error}"
            else:
                self._error = str(e)
                self._status = f"Error: {self._error}"
            logger.error(f"Failed to load model: {e}", exc_info=True)
        except Exception as e:
            self._error = str(e)
            self._status = f"Error: {self._error}"
            logger.error(f"Failed to load model: {e}", exc_info=True)
        finally:
            self._is_downloading = False
            self._loading = False
            self._ready_event.set()
            if monitor_thread:
                monitor_thread.join(timeout=2)

    def load_model_async(self):
        self._ready_event.clear()
        t = threading.Thread(target=self.load_model, daemon=True)
        t.start()

    def retry_load(self):
        """Reset state and retry model loading."""
        self._model = None
        self._loading = False
        self._error = None
        self._status = "Retrying..."
        self._download_progress = 0
        self._is_downloading = False
        self._download_speed = 0.0
        self._download_eta = 0
        self._downloaded_mb = 0.0
        self._elapsed_seconds = 0
        self._speed_samples = []
        self.load_model_async()

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    @property
    def is_loading(self) -> bool:
        return self._loading

    @property
    def is_downloading(self) -> bool:
        return self._is_downloading

    @property
    def has_error(self) -> bool:
        return self._error is not None

    def get_status(self) -> dict:
        """Return current loading status for the UI."""
        speed_mbs = self._download_speed / (1024 * 1024) if self._download_speed else 0.0

        if self._loading and self._load_start_time > 0:
            self._elapsed_seconds = int(time.time() - self._load_start_time)

        return {
            "message": self._status,
            "progress": self._download_progress,
            "downloading": self._is_downloading,
            "loading": self._loading,
            "ready": self.is_ready,
            "error": self._error,
            "speed_mbs": round(speed_mbs, 1),
            "eta_seconds": self._download_eta,
            "downloaded_mb": round(self._downloaded_mb, 1),
            "total_mb": round(self._total_mb, 1),
            "elapsed_seconds": self._elapsed_seconds,
        }

    def wait_until_ready(self, timeout=None) -> bool:
        self._ready_event.wait(timeout=timeout)
        return self.is_ready

    @staticmethod
    def _extract_text(result) -> str:
        """Extract text from gigaam transcribe() result, handling API variations.

        Different gigaam versions return:
        - str: just the text
        - tuple: (text, tokens) or (text, tokens, timestamps)
        - list: list of segments
        """
        if isinstance(result, str):
            return result
        if isinstance(result, tuple):
            return str(result[0])
        if isinstance(result, list):
            return " ".join(str(r) for r in result)
        return str(result)

    def _transcribe_short(self, audio_path: str) -> str:
        """Transcribe a short audio file (<25s) using standard method."""
        logger.info("Using transcribe (short)...")
        result = self._model.transcribe(audio_path)
        return self._extract_text(result)

    def _split_wav(self, audio_path: str, chunk_seconds: float = 20.0) -> list[str]:
        """Split a WAV file into chunks of chunk_seconds length.

        Returns list of temporary chunk file paths.
        """
        import wave
        import tempfile

        chunks = []
        with wave.open(audio_path, "rb") as wf:
            params = wf.getparams()
            sr = wf.getframerate()
            total_frames = wf.getnframes()
            chunk_frames = int(chunk_seconds * sr)

            idx = 0
            while wf.tell() < total_frames:
                frames_to_read = min(chunk_frames, total_frames - wf.tell())
                data = wf.readframes(frames_to_read)

                chunk_path = tempfile.mktemp(suffix=f"_chunk{idx}.wav")
                with wave.open(chunk_path, "wb") as cw:
                    cw.setparams(params)
                    cw.writeframes(data)
                chunks.append(chunk_path)
                idx += 1

        logger.info(f"Split audio into {len(chunks)} chunks of ~{chunk_seconds}s")
        return chunks

    def _transcribe_long(self, audio_path: str) -> str:
        """Transcribe a long audio file (>25s) using longform method with fallback."""
        logger.info("Using transcribe_longform...")
        try:
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
            return self._extract_text(result)
        except (ImportError, ModuleNotFoundError, ValueError) as e:
            logger.warning(f"Longform transcription unavailable ({e}), falling back to chunked transcribe")
            return self._transcribe_chunked(audio_path)
        except FileNotFoundError as e:
            logger.warning(f"Longform transcription failed ({e}), falling back to chunked transcribe")
            return self._transcribe_chunked(audio_path)

    def _transcribe_chunked(self, audio_path: str) -> str:
        """Split long audio into chunks and transcribe each one."""
        import os

        chunks = self._split_wav(audio_path)
        texts = []
        try:
            for i, chunk_path in enumerate(chunks):
                logger.info(f"Transcribing chunk {i + 1}/{len(chunks)}: {chunk_path}")
                try:
                    result = self._model.transcribe(chunk_path)
                    text = self._extract_text(result).strip()
                    if text:
                        texts.append(text)
                except Exception as e:
                    logger.warning(f"Chunk {i + 1} failed: {e}")
        finally:
            for chunk_path in chunks:
                try:
                    os.unlink(chunk_path)
                except OSError:
                    pass

        combined = " ".join(texts)
        logger.info(f"Chunked transcription: {len(chunks)} chunks -> {len(combined)} chars")
        return combined

    def transcribe(self, audio_path: str) -> str:
        if not self.is_ready:
            raise RuntimeError("Model not loaded yet")

        logger.info(f"Transcribing: {audio_path}")
        duration = get_wav_duration(audio_path)
        logger.info(f"Audio duration: {duration:.1f}s")

        if duration > LONGFORM_THRESHOLD:
            return self._transcribe_long(audio_path)
        else:
            return self._transcribe_short(audio_path)
