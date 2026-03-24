"""Monkey-patch GigaAM's load_audio to avoid requiring ffmpeg binary.

GigaAM hardcodes a subprocess call to ffmpeg in gigaam.preprocess.load_audio().
This module replaces it with a torchaudio-based implementation that works
without ffmpeg installed on the system.

Must be called AFTER gigaam is imported but BEFORE any transcription.
"""
import logging

import numpy as np
import torch

logger = logging.getLogger(__name__)

_patched = False


def load_audio_no_ffmpeg(audio_path: str, sample_rate: int = 16000) -> torch.Tensor:
    """Load audio file using torchaudio instead of ffmpeg subprocess.

    Falls back to scipy/wave for WAV files if torchaudio also fails.
    """
    # Try torchaudio first (handles many formats without ffmpeg)
    try:
        import torchaudio
        wav, sr = torchaudio.load(audio_path)
        # Convert to mono if stereo
        if wav.shape[0] > 1:
            wav = wav.mean(dim=0, keepdim=True)
        # Resample if needed
        if sr != sample_rate:
            resampler = torchaudio.transforms.Resample(sr, sample_rate)
            wav = resampler(wav)
        return wav[0]  # Remove channel dim → 1D tensor
    except Exception as e:
        logger.debug(f"torchaudio.load failed: {e}, trying wave module")

    # Fallback: use stdlib wave module (WAV only)
    import wave
    with wave.open(audio_path, "rb") as wf:
        sr = wf.getframerate()
        n_frames = wf.getnframes()
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        raw = wf.readframes(n_frames)

    if sampwidth == 2:
        dtype = np.int16
    elif sampwidth == 4:
        dtype = np.int32
    else:
        dtype = np.int16

    audio = np.frombuffer(raw, dtype=dtype).astype(np.float32)

    # Convert to mono
    if n_channels > 1:
        audio = audio.reshape(-1, n_channels).mean(axis=1)

    # Normalize to [-1, 1]
    max_val = float(np.iinfo(dtype).max)
    audio = audio / max_val

    wav = torch.from_numpy(audio)

    # Resample if needed
    if sr != sample_rate:
        try:
            import torchaudio
            resampler = torchaudio.transforms.Resample(sr, sample_rate)
            wav = resampler(wav.unsqueeze(0))[0]
        except Exception:
            # Simple linear interpolation as last resort
            ratio = sample_rate / sr
            n_samples = int(len(wav) * ratio)
            indices = torch.linspace(0, len(wav) - 1, n_samples)
            wav = torch.from_numpy(
                np.interp(indices.numpy(), np.arange(len(wav)), wav.numpy())
            ).float()

    return wav


def patch_gigaam():
    """Replace gigaam.preprocess.load_audio with our ffmpeg-free version."""
    global _patched
    if _patched:
        return

    try:
        # Use sys.modules lookup to handle both real packages and bundled environments
        import sys as _sys
        preprocess = _sys.modules.get("gigaam.preprocess")
        if preprocess is None:
            import gigaam.preprocess
            preprocess = gigaam.preprocess
        preprocess.load_audio = load_audio_no_ffmpeg
        logger.info("Patched gigaam.preprocess.load_audio (no ffmpeg needed)")
        _patched = True
    except (ImportError, AttributeError) as e:
        logger.warning(f"Could not patch gigaam.preprocess: {e}")
