import json
import logging
import subprocess
import time
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You clean Russian speech-to-text transcripts. You ONLY do three things:

1. DELETE FILLER WORDS — words that are verbal pauses with zero meaning:
   - ALWAYS delete these sounds/stutters: э, эм, э-э, м-м, а-а, хм, и-и-и, а-а-а, э-э-э, ммм. Also delete repeated/stuttered words like "я я думаю" → "я думаю".
   - DELETE "как бы" — almost always a filler in spoken Russian. Keep ONLY when it literally means "as if" in a comparison.
   - DELETE "ну" when it starts a sentence as a pause. Keep in "Ну и дела!", "Ну что ж".
   - DELETE "вот" when used as a pause between phrases. Keep when pointing: "Вот этот файл".
   - DELETE: типа, значит, короче, в общем, так сказать, по сути дела, по сути, на самом деле — when they are pauses.
   - DELETE "то есть" when followed by a pause word or filler. Keep when it introduces a real clarification.
   - DELETE combinations of fillers: "то есть, ну", "ну, вот", "вот, э-э" — delete the entire filler chain.
   - After deleting fillers, fix leftover double spaces and dangling commas.

2. FIX PUNCTUATION: Add commas, periods, question marks. Capitalize sentence starts. Do NOT change word order.

3. FIX ASR ERRORS — this is critical:
   - The speaker often mixes Russian and English words. When you see misspelled English in Russian text, fix the spelling. Example: "rady to youse" → "ready to use", "ваф" → "WAV".
   - Fix obviously wrong Russian words where a phonetically similar word clearly fits.
   - KEEP proper English words, technical terms, brand names as-is.
   - NEVER change names of people or products.

RULES:
- NEVER add words the speaker did not say
- NEVER rephrase or improve the language
- NEVER remove meaningful words
- Output ONLY the cleaned text, no comments"""


def clean_text_with_llm(text: str, timeout: float = 30.0) -> str:
    """Clean ASR transcript using Gemma via Ollama.

    Returns cleaned text, or original text if Ollama is unavailable.
    """
    if not text or not text.strip():
        return text

    try:
        start = time.time()

        payload = {
            "model": "gemma3:4b",
            "system": SYSTEM_PROMPT,
            "prompt": text,
            "stream": False,
            "options": {
                "temperature": 0.1,  # Low temperature for conservative edits
                "top_p": 0.9,
                "num_predict": len(text) * 2,  # Don't generate more than 2x input
            }
        }

        result = subprocess.run(
            ["curl", "-s", "--max-time", str(int(timeout)),
             "http://localhost:11434/api/generate",
             "-d", json.dumps(payload)],
            capture_output=True, text=True, timeout=timeout + 5
        )

        if result.returncode != 0:
            logger.warning(f"Ollama request failed: {result.stderr}")
            return text

        response = json.loads(result.stdout)
        cleaned = response.get("response", "").strip()

        elapsed = time.time() - start
        logger.info(f"LLM cleanup in {elapsed:.1f}s: '{text[:50]}...' → '{cleaned[:50]}...'")

        # Safety check: if the cleaned text is suspiciously different, return original
        if not cleaned:
            logger.warning("LLM returned empty response, using original")
            return text

        # If cleaned text is more than 30% longer than original, likely hallucination
        if len(cleaned) > len(text) * 1.3:
            logger.warning(f"LLM output suspiciously longer ({len(cleaned)} vs {len(text)}), using original")
            return text

        return cleaned

    except subprocess.TimeoutExpired:
        logger.warning("Ollama timed out")
        return text
    except json.JSONDecodeError:
        logger.warning("Ollama returned invalid JSON")
        return text
    except Exception as e:
        logger.warning(f"LLM cleanup failed: {e}")
        return text


def clean_text_with_openrouter(text: str, api_key: str, model: str = "google/gemma-3-4b-it:free", timeout: float = 30.0) -> str:
    """Clean ASR transcript using OpenRouter API.

    Returns cleaned text, or original text if API call fails.
    """
    if not text or not text.strip():
        return text

    if not api_key:
        logger.warning("OpenRouter API key not set")
        return text

    try:
        start = time.time()

        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "temperature": 0.1,
            "top_p": 0.9,
            "max_tokens": len(text) * 2,
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        cleaned = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

        elapsed = time.time() - start
        logger.info(f"OpenRouter cleanup in {elapsed:.1f}s: '{text[:50]}...' → '{cleaned[:50]}...'")

        if not cleaned:
            logger.warning("OpenRouter returned empty response, using original")
            return text

        if len(cleaned) > len(text) * 1.3:
            logger.warning(f"OpenRouter output suspiciously longer ({len(cleaned)} vs {len(text)}), using original")
            return text

        return cleaned

    except urllib.error.HTTPError as e:
        logger.warning(f"OpenRouter HTTP error {e.code}: {e.reason}")
        return text
    except Exception as e:
        logger.warning(f"OpenRouter cleanup failed: {e}")
        return text


def clean_text(text: str, config, timeout: float = 30.0) -> str:
    """Dispatch text cleanup to the configured LLM provider."""
    if not config.get("llm_cleanup", True):
        return text

    provider = config.get("llm_provider", "local")

    if provider == "openrouter":
        api_key = config.get("openrouter_api_key", "")
        model = config.get("openrouter_model", "google/gemma-3-4b-it:free")
        if api_key:
            return clean_text_with_openrouter(text, api_key, model, timeout)
        else:
            logger.warning("OpenRouter selected but no API key set, skipping cleanup")
            return text
    else:
        # Local Ollama
        if is_ollama_available():
            return clean_text_with_llm(text, timeout)
        return text


def is_ollama_available() -> bool:
    """Check if Ollama is running and Gemma model is available."""
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "2", "http://localhost:11434/api/tags"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return False
        data = json.loads(result.stdout)
        models = [m.get("name", "") for m in data.get("models", [])]
        return any("gemma3" in m for m in models)
    except Exception:
        return False
