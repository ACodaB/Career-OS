"""
Thin wrapper around the Gemini API. Later phases (matching, resume tailoring,
cover letters, company research, interview prep) all call through this
instead of touching the SDK directly, so there's one place to change if the
SDK or model name ever changes.
"""
from google import genai

from app.config import settings

_client = genai.Client(api_key=settings.gemini_api_key)


def generate_text(prompt: str, system_instruction: str | None = None) -> str:
    """Simple text-in, text-out call. Used for cover letters, company briefs, etc."""
    response = _client.models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
        config={"system_instruction": system_instruction} if system_instruction else None,
    )
    return response.text


def generate_json(prompt: str, system_instruction: str | None = None) -> str:
    """
    Same as generate_text, but asks Gemini to return valid JSON only.
    Used for structured outputs like match scores (Phase 2) — caller is
    responsible for parsing/validating the returned string with Pydantic.
    """
    response = _client.models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
        config={
            "system_instruction": system_instruction,
            "response_mime_type": "application/json",
        },
    )
    return response.text


def embed_text(text: str) -> list[float]:
    """Returns an embedding vector for a piece of text (resume bullets, JDs, etc.)."""
    response = _client.models.embed_content(
        model=settings.gemini_embedding_model,
        contents=text,
    )
    return response.embeddings[0].values
