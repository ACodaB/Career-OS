""""
Thin wrapper around the LLM providers. Later phases (matching, resume
tailoring, cover letters, company research, interview prep) all call
through this instead of touching either SDK directly, so there's one
place to change if a provider or model name ever changes.
 
Split by capability:
  - Text/JSON generation -> Groq (llama-3.3-70b-versatile). Fast, free-tier
    friendly, and this is where quality of writing matters most
    (application prep) and where matching reasoning happens.
  - Embeddings -> Gemini (gemini-embedding-001). Groq has no embedding
    endpoint as of this writing, so embeddings stay on Gemini. This is
    the ONLY thing the Gemini client is still used for.
"""
from google import genai
from groq import Groq
 
from app.config import settings
 
_groq_client = Groq(api_key=settings.groq_api_key)
_gemini_client = genai.Client(api_key=settings.gemini_api_key)
 
 
def generate_text(prompt: str, system_instruction: str | None = None) -> str:
    """Simple text-in, text-out call. Used for cover letters, company briefs, etc."""
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})
 
    response = _groq_client.chat.completions.create(
        model=settings.groq_model,
        messages=messages,
    )
    return response.choices[0].message.content
 
 
def generate_json(prompt: str, system_instruction: str | None = None) -> str:
    """
    Same as generate_text, but asks the model to return valid JSON only.
    Used for structured outputs like match scores (Phase 2) and
    tailored-application content (Phase 3) — caller is responsible for
    parsing/validating the returned string.
 
    Groq's JSON mode requires the word "JSON" to appear somewhere in the
    prompt/system instruction, so we make sure of that here regardless of
    what the caller passed in.
    """
    json_reminder = (
        "Respond with valid JSON only — no markdown code fences, no "
        "commentary outside the JSON object."
    )
    combined_system = (
        f"{system_instruction}\n\n{json_reminder}" if system_instruction else json_reminder
    )
 
    messages = [
        {"role": "system", "content": combined_system},
        {"role": "user", "content": prompt},
    ]
 
    response = _groq_client.chat.completions.create(
        model=settings.groq_model,
        messages=messages,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content
 
 
def embed_text(text: str) -> list[float]:
    """
    Returns an embedding vector for a piece of text (resume bullets, JDs,
    etc). Stays on Gemini — Groq does not currently offer an embedding
    endpoint.
    """
    response = _gemini_client.models.embed_content(
        model=settings.gemini_embedding_model,
        contents=text,
    )
    return response.embeddings[0].values