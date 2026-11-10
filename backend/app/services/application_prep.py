"""
Phase 3 — Application prep.

Given a Job and the user's UserProfile, asks the LLM to produce:
  1. A tailored version of the resume content, rewritten/reordered to
     emphasize the experience most relevant to this specific job.
  2. A cover letter for this specific job.

Both are returned as a single JSON object from one LLM call (cheaper and
faster than two separate calls, and keeps the two documents consistent
with each other).

Includes retry/backoff on rate-limit (429) errors, matching the resilience
pattern already used in matching.py.
"""
import json
import time
from datetime import datetime,timezone

from sqlalchemy.orm import Session

from app.models import Job, UserProfile
from app.llm import generate_json


SYSTEM_INSTRUCTION = (
    "You are an expert resume writer and career coach. You write in a natural, "
    "confident, human voice — not generic corporate filler. You never invent "
    "experience, employers, titles, or skills the candidate doesn't have; you only "
    "reorder, re-emphasize, and rephrase what's actually in their resume to better "
    "match the target job. Respond with valid JSON only, no markdown code fences, "
    "no commentary outside the JSON object."
)

MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 2.0


def _build_prompt(job: Job, profile: UserProfile) -> str:
    return f"""Candidate resume (LaTeX source; the ONLY source of facts about the candidate. Do not invent anything that is not in here):
---
{profile.resume_text}
---
Candidate skills: {profile.skills}

Target job:
Company: {job.company}
Title: {job.title}
Location: {job.location}
Description:
---
{job.description}
---

Produce a JSON object with exactly two keys:

"tailored_resume": the candidate's resume tailored to this job, written in the plain-text
"resume markup" described below (NOT LaTeX). It is turned into a PDF that must look like
the source resume, so follow this format exactly:
- Do NOT include the name, contact line, or header links. They are added automatically.
- Start every section with "## " followed by the section title, using the same section
  titles and the same order as the source (for example Experience, Skills, Projects,
  Education, Achievements, Certifications).
- An entry heading (a job, project, or degree) is one line: "### Left text | Right text",
  for example "### AI Intern -- Company | Jul 2026 – Aug 2026" or
  "### Project Name | AI/ML Developer".
- Bullets start with "- ". Use **double asterisks** for bold (a bullet's lead-in label and
  its key metrics, as in the source) and *single asterisks* for italics. A second line
  inside the same bullet goes on its own line, indented by two spaces.
- In the Skills section write one line per category, like "Languages: Python, C/C++, SQL".
  Reorder the items within a line so the ones most relevant to this job come first. Only
  list skills that appear in the source.
- Other lines under an entry (such as Tech Stack or GitHub) are plain lines, for example
  "**Tech Stack:** Python, SQL" and "**GitHub:** github.com/ACodaB/Automl-project".
  Copy link text EXACTLY as written in the source so it becomes a clickable link.
- Plain text only: no LaTeX commands or backslashes. Write % and & normally and use an
  en dash (–) for ranges.
- Tailor by putting the most relevant bullets, projects and skills first and lightly
  rewording with the job's own vocabulary. You may drop the least relevant bullets or
  entries to keep the length close to the source. Keep every number, date, employer,
  title and degree exactly as in the source. Never invent anything.
- Use "\\n" for line breaks within the string.

"cover_letter": a complete, ready-to-send cover letter (3-4 short paragraphs) for
this specific job at this specific company, written in first person, referencing
concrete details from both the resume and the job description. Use "\\n\\n" between
paragraphs within the string.

Return only the JSON object."""


def _call_with_retry(prompt: str) -> str:
    """
    Calls generate_json with exponential backoff on rate-limit errors.
    Groq/Gemini SDKs raise different exception types for 429s, so we check
    the string representation of the error rather than importing every
    possible exception class — same pragmatic approach matching.py uses.
    """
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
                f"[application_prep] Rate limited (attempt {attempt}/{MAX_RETRIES}), "
                f"backing off {backoff:.1f}s..."
            )
            time.sleep(backoff)
            backoff *= 2

    # Should be unreachable (loop either returns or raises), but keeps type
    # checkers happy and guards against future refactors of the loop above.
    raise last_error


def generate_application(db: Session, job: Job, profile: UserProfile) -> Job:
    """
    Calls the LLM to generate a tailored resume + cover letter for `job`,
    saves the result onto the Job row, and returns the updated Job.

    Raises ValueError if the model's response isn't valid JSON or is
    missing the expected keys, so the caller (main.py) can turn that into
    a clean 500 instead of a raw crash.
    """
    prompt = _build_prompt(job, profile)
    raw = _call_with_retry(prompt)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model did not return valid JSON: {e}")

    tailored_resume = data.get("tailored_resume")
    cover_letter = data.get("cover_letter")

    if not tailored_resume or not cover_letter:
        raise ValueError(
            "Model response was missing 'tailored_resume' or 'cover_letter'."
        )

    job.tailored_resume = tailored_resume
    job.tailored_cover_letter = cover_letter
    job.application_generated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(job)
    return job