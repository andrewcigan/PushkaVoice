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
    """Replace gigaam.preprocess.load_audio with our ffmpeg-free version.

    GigaAM modules may import load_audio via 'from .preprocess import load_audio',
    copying the function reference into their own namespace. We must patch
    every module that holds a reference to the original function.
    """
    global _patched
    if _patched:
        return

    import sys as _sys
    patched_count = 0

    # Patch gigaam.preprocess.load_audio (the source)
    try:
        preprocess = _sys.modules.get("gigaam.preprocess")
        if preprocess is None:
            import gigaam.preprocess
            preprocess = gigaam.preprocess
        if hasattr(preprocess, "load_audio"):
            preprocess.load_audio = load_audio_no_ffmpeg
            patched_count += 1
    except (ImportError, AttributeError) as e:
        logger.warning(f"Could not patch gigaam.preprocess: {e}")

    # Patch any other gigaam module that imported load_audio
    # (e.g. gigaam.model does 'from .preprocess import load_audio')
    for mod_name, mod in list(_sys.modules.items()):
        if not mod_name.startswith("gigaam.") or mod is None:
            continue
        if mod_name == "gigaam.preprocess":
            continue  # already patched above
        try:
            if hasattr(mod, "load_audio") and callable(getattr(mod, "load_audio", None)):
                current = getattr(mod, "load_audio")
                if current is not load_audio_no_ffmpeg:
                    setattr(mod, "load_audio", load_audio_no_ffmpeg)
                    patched_count += 1
                    logger.info(f"Patched {mod_name}.load_audio")
        except Exception:
            pass

    if patched_count > 0:
        logger.info(f"Patched load_audio in {patched_count} gigaam module(s) (no ffmpeg needed)")
        _patched = True
    else:
        logger.warning("Could not find any gigaam modules to patch")
