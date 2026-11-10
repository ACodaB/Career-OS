"""
Phase 6 — Essay answer drafting.

Given the free-text application questions found on a form (from the
autofill runner's scan mode), drafts one answer per question using the
candidate's resume and the job description.

Answers are DRAFTS for the user to review and edit. Nothing here talks to
the browser or submits anything.

Returns a list aligned 1:1 with the input questions:
    [{"question": str, "answer": str, "has_direct_experience": bool}, ...]
"""
import json
import re
import time

from app.llm import generate_json

SYSTEM_INSTRUCTION = (
    "You are an expert career coach helping a candidate answer free-text "
    "job application questions. You write in a natural, specific, confident "
    "first-person voice, with no corporate filler and no clichés. You NEVER "
    "invent experience, employers, projects, metrics, or skills that are not "
    "in the candidate's resume. If the resume has nothing directly relevant to "
    "a question, you answer honestly using the closest real experience and "
    "genuine interest, and you mark that answer as not having direct "
    "experience. Respond with valid JSON only, no markdown code fences, no "
    "commentary outside the JSON object."
)

MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 2.0
MAX_DESCRIPTION_CHARS = 6000


def _coerce_to_dict(result) -> dict:
    """generate_json can return a dict, a list, or a JSON string. Normalize."""
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        return {"answers": result}
    if isinstance(result, str):
        text = result.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I).strip()
        parsed = json.loads(text)
        if isinstance(parsed, (dict, list)):
            return _coerce_to_dict(parsed)
    raise ValueError("Model response could not be parsed as JSON.")


def _build_prompt(company, title, description, resume_text, cover_letter, questions) -> str:
    numbered = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))
    letter_block = (
        f"\nCover letter already written for this job (keep answers consistent "
        f"with it, do not repeat it):\n---\n{cover_letter}\n---\n"
        if cover_letter
        else ""
    )
    return f"""Candidate resume (the ONLY source of facts about the candidate):
---
{resume_text}
---
{letter_block}
Target job:
Company: {company}
Title: {title}
Description:
---
{(description or "")[:MAX_DESCRIPTION_CHARS]}
---

Application questions to answer:
{numbered}

Rules for every answer:
- First person, plain text, no markdown, no bullet points, no headings.
- About 100 to 180 words unless the question clearly needs less.
- Reference concrete things from the resume and the job or company. Do not
  invent facts, numbers, projects, or employers.
- "Why do you want to work at <company>" style questions: tie the candidate's
  real background to what the company actually does, based on the job
  description. No flattery or generic praise.
- If the resume has no directly relevant experience for a question, say so
  honestly, bridge from the closest real experience, and set
  "has_direct_experience" to false.

Return a JSON object with exactly one key, "answers": an array with exactly
{len(questions)} items, in the same order as the questions above. Each item:
{{"answer": "<the answer text>", "has_direct_experience": true or false}}

Return only the JSON object."""


def _call_with_retry(prompt: str):
    backoff = INITIAL_BACKOFF_SECONDS
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return generate_json(prompt, system_instruction=SYSTEM_INSTRUCTION)
        except Exception as e:
            error_text = str(e).lower()
            is_rate_limit = (
                "429" in error_text
                or "rate limit" in error_text
                or "resource_exhausted" in error_text
                or "too many requests" in error_text
            )
            if not is_rate_limit or attempt == MAX_RETRIES:
                raise
            last_error = e
            print(
                f"[essay_answers] Rate limited (attempt {attempt}/{MAX_RETRIES}), "
                f"backing off {backoff:.1f}s..."
            )
            time.sleep(backoff)
            backoff *= 2
    raise last_error


def draft_answers(
    company: str,
    title: str,
    description: str,
    resume_text: str,
    cover_letter: str,
    questions: list[str],
) -> list[dict]:
    """Core function: plain strings in, aligned list of drafted answers out."""
    if not questions:
        return []
    if not (resume_text or "").strip():
        raise ValueError("No resume text available to ground the answers.")

    prompt = _build_prompt(company, title, description, resume_text, cover_letter, questions)
    data = _coerce_to_dict(_call_with_retry(prompt))

    items = data.get("answers")
    if not isinstance(items, list) or len(items) != len(questions):
        raise ValueError(
            f"Model returned {len(items) if isinstance(items, list) else 'no'} answers "
            f"for {len(questions)} questions. Try again."
        )

    results = []
    for question, item in zip(questions, items):
        if isinstance(item, str):  # tolerate a bare-string answer
            item = {"answer": item, "has_direct_experience": True}
        answer = str(item.get("answer", "")).strip()
        if not answer:
            raise ValueError("Model returned an empty answer. Try again.")
        results.append(
            {
                "question": question,  # exact original text, needed for form matching
                "answer": answer,
                "has_direct_experience": bool(item.get("has_direct_experience", True)),
            }
        )
    return results


def draft_essay_answers(job, profile, questions: list[str]) -> list[dict]:
    """Convenience wrapper for the API layer: takes Job + UserProfile rows."""
    resume_text = (getattr(job, "tailored_resume", "") or "").strip() or profile.resume_text
    return draft_answers(
        company=job.company,
        title=job.title,
        description=job.description,
        resume_text=resume_text,
        cover_letter=getattr(job, "tailored_cover_letter", "") or "",
        questions=questions,
    )