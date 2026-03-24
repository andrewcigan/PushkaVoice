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


def patch_gigaam(model=None):
    """Replace gigaam's load_audio with our ffmpeg-free version.

    GigaAM uses ffmpeg subprocess to decode audio files. We replace the
    load_audio function at every level where it might be referenced:
    1. gigaam.preprocess module (the source definition)
    2. Any gigaam.* module that imported it (e.g. gigaam.model, gigaam.vad_utils)
    3. The model object's prepare_wav method (if model is provided)

    This must be called AFTER gigaam.load_model() so all submodules are loaded.
    """
    global _patched
    if _patched:
        return

    import sys as _sys
    patched_count = 0

    # 1. Patch gigaam.preprocess.load_audio (the source)
    original_load_audio = None
    try:
        preprocess = _sys.modules.get("gigaam.preprocess")
        if preprocess is None:
            import gigaam.preprocess
            preprocess = gigaam.preprocess
        if hasattr(preprocess, "load_audio"):
            original_load_audio = preprocess.load_audio
            preprocess.load_audio = load_audio_no_ffmpeg
            patched_count += 1
            logger.info("Patched gigaam.preprocess.load_audio")
    except (ImportError, AttributeError) as e:
        logger.warning(f"Could not patch gigaam.preprocess: {e}")

    # 2. Patch any other gigaam module that imported load_audio
    for mod_name, mod in list(_sys.modules.items()):
        if not mod_name.startswith("gigaam.") or mod is None:
            continue
        if mod_name == "gigaam.preprocess":
            continue
        try:
            if hasattr(mod, "load_audio") and callable(getattr(mod, "load_audio", None)):
                current = getattr(mod, "load_audio")
                if current is not load_audio_no_ffmpeg:
                    setattr(mod, "load_audio", load_audio_no_ffmpeg)
                    patched_count += 1
                    logger.info(f"Patched {mod_name}.load_audio")
        except Exception:
            pass

    # 3. Monkey-patch the model's prepare_wav to use our load_audio
    if model is not None:
        try:
            import types

            original_prepare_wav = model.prepare_wav

            def patched_prepare_wav(audio_path, *args, **kwargs):
                audio = load_audio_no_ffmpeg(audio_path)
                return audio

            # Bind as method if original was a method
            if hasattr(original_prepare_wav, '__self__'):
                model.prepare_wav = types.MethodType(
                    lambda self, audio_path, *a, **kw: load_audio_no_ffmpeg(audio_path),
                    model
                )
            else:
                model.prepare_wav = patched_prepare_wav
            patched_count += 1
            logger.info("Patched model.prepare_wav directly")
        except Exception as e:
            logger.warning(f"Could not patch model.prepare_wav: {e}")

    if patched_count > 0:
        logger.info(f"Patched load_audio in {patched_count} location(s) (no ffmpeg needed)")
        _patched = True
    else:
        logger.warning("Could not find any gigaam modules to patch")
