"""Monkey-patch GigaAM's load_audio to avoid requiring ffmpeg binary.

GigaAM hardcodes a subprocess call to ffmpeg in gigaam.preprocess.load_audio().
This module replaces it with a torchaudio-based implementation that works
without ffmpeg installed on the system.

Must be called AFTER gigaam is imported but BEFORE any transcription.

Strategy: we patch subprocess.run so that when gigaam tries to call ffmpeg,
we intercept it and decode the audio ourselves. This is more robust than
trying to patch individual functions in gigaam's internals.
"""
import logging
import subprocess
import wave as wave_mod

import numpy as np
import torch

logger = logging.getLogger(__name__)

_patched = False


def _decode_audio_without_ffmpeg(cmd, **kwargs):
    """Intercept ffmpeg subprocess calls and decode audio using Python.

    GigaAM calls ffmpeg like:
        ffmpeg -nostdin -threads 0 -i <path> -f s16le -ac 1 -acodec pcm_s16le -ar 16000 -

    We parse the command, read the WAV file, and return the raw PCM bytes
    that ffmpeg would have produced.
    """
    # Parse the ffmpeg command to extract input file and target sample rate
    if not isinstance(cmd, (list, tuple)) or len(cmd) < 2:
        raise FileNotFoundError("Not an ffmpeg command")

    if cmd[0] != "ffmpeg":
        raise FileNotFoundError(f"Not ffmpeg: {cmd[0]}")

    # Extract -i <input_file> and -ar <sample_rate>
    input_file = None
    target_sr = 16000
    for i, arg in enumerate(cmd):
        if arg == "-i" and i + 1 < len(cmd):
            input_file = cmd[i + 1]
        elif arg == "-ar" and i + 1 < len(cmd):
            try:
                target_sr = int(cmd[i + 1])
            except ValueError:
                pass

    if input_file is None:
        raise FileNotFoundError("Could not parse ffmpeg command: no input file")

    logger.debug(f"Intercepted ffmpeg call: input={input_file}, target_sr={target_sr}")

    # Try torchaudio first
    try:
        import torchaudio
        wav, sr = torchaudio.load(input_file)
        if wav.shape[0] > 1:
            wav = wav.mean(dim=0, keepdim=True)
        if sr != target_sr:
            resampler = torchaudio.transforms.Resample(sr, target_sr)
            wav = resampler(wav)
        # Convert to int16 PCM (s16le) — what ffmpeg would output with -f s16le
        pcm = (wav[0] * 32767).clamp(-32768, 32767).to(torch.int16)
        raw_bytes = pcm.numpy().tobytes()
        logger.debug(f"Decoded via torchaudio: {len(raw_bytes)} bytes, sr={target_sr}")
        result = subprocess.CompletedProcess(cmd, 0, stdout=raw_bytes, stderr=b"")
        return result
    except Exception as e:
        logger.debug(f"torchaudio failed: {e}, trying wave module")

    # Fallback: stdlib wave module (WAV files only)
    with wave_mod.open(input_file, "rb") as wf:
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

    if n_channels > 1:
        audio = audio.reshape(-1, n_channels).mean(axis=1)

    # Normalize
    max_val = float(np.iinfo(dtype).max)
    audio = audio / max_val

    # Resample if needed
    if sr != target_sr:
        try:
            import torchaudio
            t = torch.from_numpy(audio).unsqueeze(0)
            resampler = torchaudio.transforms.Resample(sr, target_sr)
            audio = resampler(t)[0].numpy()
        except Exception:
            ratio = target_sr / sr
            n_samples = int(len(audio) * ratio)
            indices = np.linspace(0, len(audio) - 1, n_samples)
            audio = np.interp(indices, np.arange(len(audio)), audio)

    # Convert to int16 PCM bytes (s16le format)
    pcm = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
    raw_bytes = pcm.tobytes()

    logger.debug(f"Decoded via wave module: {len(raw_bytes)} bytes, sr={target_sr}")
    result = subprocess.CompletedProcess(cmd, 0, stdout=raw_bytes, stderr=b"")
    return result


# Keep a reference to the real subprocess.run
_original_subprocess_run = subprocess.run


def _patched_subprocess_run(cmd, *args, **kwargs):
    """Wrapper around subprocess.run that intercepts ffmpeg calls."""
    if isinstance(cmd, (list, tuple)) and len(cmd) > 0 and cmd[0] == "ffmpeg":
        try:
            return _decode_audio_without_ffmpeg(cmd, **kwargs)
        except Exception as e:
            logger.warning(f"ffmpeg interception failed: {e}, trying original")
    return _original_subprocess_run(cmd, *args, **kwargs)


def patch_gigaam(model=None):
    """Patch subprocess.run to intercept ffmpeg calls from GigaAM.

    This is the nuclear option — instead of trying to patch individual
    functions in gigaam's internals (which fail due to frozen imports,
    closures, and copied references), we intercept at the subprocess level.

    When GigaAM calls subprocess.run(["ffmpeg", ...]), we decode the audio
    ourselves using torchaudio or stdlib wave module.
    """
    global _patched
    if _patched:
        return

    subprocess.run = _patched_subprocess_run
    logger.info("Patched subprocess.run to intercept ffmpeg calls (no ffmpeg needed)")
    _patched = True


