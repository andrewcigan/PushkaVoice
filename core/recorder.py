import logging
import tempfile
import threading
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16000  # GigaAM expects 16kHz


class AudioRecorder:
    def __init__(self, device_id=None, sample_rate=16000):
        self.target_sample_rate = sample_rate
        self.device_id = device_id
        self._frames = []
        self._recording = False
        self._record_thread = None
        self._lock = threading.Lock()
        self._native_sr = None

    def _get_native_sample_rate(self):
        """Get native sample rate for the device."""
        if self.device_id is not None:
            info = sd.query_devices(self.device_id)
        else:
            info = sd.query_devices(kind='input')
        return int(info['default_samplerate'])

    def start(self):
        self._frames = []
        self._recording = True
        self._native_sr = self._get_native_sample_rate()
        self._record_thread = threading.Thread(target=self._record_loop, daemon=True)
        self._record_thread.start()
        logger.info(f"Recording thread started (device={self.device_id}, native_sr={self._native_sr}, target_sr={self.target_sample_rate})")

    def _record_loop(self):
        """Record in a dedicated thread using blocking read at native sample rate."""
        chunk_duration = 0.2  # shorter chunks to avoid overflow
        chunk_frames = int(self._native_sr * chunk_duration)

        try:
            with sd.InputStream(
                samplerate=self._native_sr,
                channels=1,
                dtype="int16",
                device=self.device_id,
            ) as stream:
                logger.info(f"InputStream opened: device={stream.device}, sr={stream.samplerate}")
                while self._recording:
                    data, overflowed = stream.read(chunk_frames)
                    if overflowed:
                        logger.warning("Audio buffer overflow")
                    with self._lock:
                        self._frames.append(data.copy())
        except Exception as e:
            logger.error(f"Recording error: {e}")

    def _resample(self, audio_data, orig_sr, target_sr):
        """Simple resample by linear interpolation."""
        if orig_sr == target_sr:
            return audio_data

        ratio = target_sr / orig_sr
        n_samples = int(len(audio_data) * ratio)
        indices = np.linspace(0, len(audio_data) - 1, n_samples)
        resampled = np.interp(indices, np.arange(len(audio_data)), audio_data.flatten().astype(float))
        return resampled.astype(np.int16).reshape(-1, 1)

    def stop(self, save_dir=None) -> str:
        self._recording = False
        if self._record_thread:
            self._record_thread.join(timeout=3.0)
            self._record_thread = None

        with self._lock:
            if not self._frames:
                logger.warning("No audio frames captured!")
                return ""
            audio_data = np.concatenate(self._frames, axis=0)

        rms = np.sqrt(np.mean(audio_data.astype(float) ** 2))
        logger.info(f"Captured {len(audio_data)} samples at {self._native_sr}Hz, RMS={rms:.1f}, max={np.abs(audio_data).max()}")

        # Resample to target rate if needed
        if self._native_sr != self.target_sample_rate:
            audio_data = self._resample(audio_data, self._native_sr, self.target_sample_rate)
            logger.info(f"Resampled to {self.target_sample_rate}Hz: {len(audio_data)} samples")

        if save_dir:
            Path(save_dir).mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            wav_path = str(Path(save_dir) / f"{timestamp}.wav")
        else:
            fd, wav_path = tempfile.mkstemp(suffix=".wav")
            import os
            os.close(fd)

        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.target_sample_rate)
            wf.writeframes(audio_data.tobytes())

        logger.info(f"Saved WAV: {wav_path}")
        return wav_path

    @staticmethod
    def list_devices():
        devices = sd.query_devices()
        input_devices = []
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0:
                input_devices.append({
                    "id": i,
                    "name": d["name"],
                    "channels": d["max_input_channels"],
                    "sample_rate": int(d["default_samplerate"]),
                })
        return input_devices
