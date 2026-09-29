"""Thin wrapper around the Gemini JSON API with API-key rotation.

qualifiar.py keeps its own copy of this loop for the scraping path; this module
exists so the email tracker can share a key pool without importing job-scoring
code. The client is built lazily, so importing this module is safe even when no
Gemini key is configured — callers that never reach Gemini (the rules-only email
path) keep working.
"""

# Standard library
import itertools

# Local
from config import Config as config

_client = None
_key_cycle = None

DEFAULT_MODEL = getattr(config, "GEMINI_PRIMARY_MODEL", None) or "gemini-2.5-flash"


class GeminiUnavailableError(Exception):
    """Gemini could not answer: overloaded, unconfigured, or out of quota."""


def _api_keys() -> list[str]:
    keys = list(getattr(config, "GEMINI_API_KEYS", None) or [])
    if keys:
        return keys
    single = getattr(config, "GEMINI_API_KEY", None)
    return [single] if single else []


def is_configured() -> bool:
    return bool(_api_keys())


def _rotate():
    """Build a client on the next key in the pool."""
    global _client, _key_cycle
    from google import genai

    keys = _api_keys()
    if not keys:
        raise GeminiUnavailableError("no Gemini API key configured")
    if _key_cycle is None:
        _key_cycle = itertools.cycle(keys)
    _client = genai.Client(api_key=next(_key_cycle))
    return _client


def generate_json(system_instruction: str, contents: str, response_schema, model: str | None = None):
    """Run a structured-output prompt, rotating keys past 429s.

    Raises GeminiUnavailableError when every key is rate-limited or the model is
    overloaded (503), so callers can fall back instead of crashing the run.
    """
    from google.genai import types
    from google.genai.errors import ClientError, ServerError

    keys = _api_keys()
    if not keys:
        raise GeminiUnavailableError("no Gemini API key configured")

    client = _client or _rotate()
    for _ in range(len(keys)):
        try:
            response = client.models.generate_content(
                model=model or DEFAULT_MODEL,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=response_schema,
                ),
                contents=contents,
            )
            return response.parsed
        except ClientError as e:
            if e.code != 429:
                raise
            print("[gemini] quota hit — rotating to next key")
            client = _rotate()
        except ServerError as e:
            if e.code == 503:
                raise GeminiUnavailableError("Gemini is overloaded (503)") from e
            raise
    raise GeminiUnavailableError("all Gemini API keys exhausted their quota")
