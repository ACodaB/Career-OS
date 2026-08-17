"""
Job-to-profile matching (Phase 2) — Chroma-backed, with embedding caching,
rate-limit handling, and resumable progress.
"""
import hashlib
import math
import time
import random
from sqlalchemy.orm import Session

from app.models import UserProfile, Job
from app.llm import embed_text
from app.vectorstore import get_jobs_collection

MIN_SECONDS_BETWEEN_EMBED_CALLS = 4.5
MAX_RETRIES = 4


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _embed_with_backoff(text: str) -> list[float]:
    for attempt in range(MAX_RETRIES):
        try:
            return embed_text(text)
        except Exception as e:
            is_rate_limit = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
            if not is_rate_limit or attempt == MAX_RETRIES - 1:
                raise
            wait = (2 ** attempt) + random.uniform(0, 1)
            print(f"Rate limited, retrying in {wait:.1f}s (attempt {attempt + 1}/{MAX_RETRIES})...")
            time.sleep(wait)


def _get_or_embed_job(collection, job: Job) -> list[float]:
    """Returns the job's embedding, using the Chroma cache when the
    description hasn't changed, otherwise re-embedding and updating it."""
    text_hash = _hash_text(job.description)
    existing = collection.get(ids=[str(job.id)], include=["metadatas", "embeddings"])
    if existing["ids"] and existing["metadatas"][0].get("text_hash") == text_hash:
        return existing["embeddings"][0]  # cache hit, no API call

    embedding = _embed_with_backoff(job.description)
    collection.upsert(
        ids=[str(job.id)],
        embeddings=[embedding],
        metadatas=[{"text_hash": text_hash, "company": job.company, "title": job.title}],
    )
    time.sleep(MIN_SECONDS_BETWEEN_EMBED_CALLS)
    return embedding


def _recommendation_from_percent(percent: int) -> str:
    if percent >= 75:
        return "strong_match"
    if percent >= 50:
        return "worth_applying"
    return "weak_match"


def match_all_jobs(
    db: Session,
    profile: UserProfile,
    only_unmatched: bool = True,
    limit: int | None = None,
    companies: list[str] | None = None,
) -> dict:
    if not profile.resume_text:
        return {"updated": 0, "remaining": 0}

    query = db.query(Job).filter(Job.description != "")
    if only_unmatched:
        query = query.filter((Job.match_percent == 0) | (Job.match_percent.is_(None)))
    if companies:
        # OR across all provided company tokens, case-insensitive substring match
        from sqlalchemy import or_
        conditions = [Job.company.ilike(f"%{c}%") for c in companies]
        query = query.filter(or_(*conditions))
    jobs = query.all()

    total_eligible = len(jobs)
    if limit:
        jobs = jobs[:limit]

    if not jobs:
        return {"updated": 0, "remaining": 0}

    collection = get_jobs_collection()
    profile_embedding = _embed_with_backoff(profile.resume_text)

    updated = 0
    for i, job in enumerate(jobs, start=1):
        if not job.description:
            continue

        job_embedding = _get_or_embed_job(collection, job)
        similarity = _cosine_similarity(profile_embedding, job_embedding)
        percent = round(max(0.0, min(1.0, similarity)) * 100)

        job.match_percent = percent
        job.match_recommendation = _recommendation_from_percent(percent)
        job.match_reasoning = {
            "similarity_percent": percent,
            "note": "Cosine similarity between resume and job description embeddings (Chroma, cached).",
        }
        db.commit()
        updated += 1
        print(f"Matched {i}/{len(jobs)}: {job.company} — {job.title} ({percent}%)")

    return {"updated": updated, "remaining": max(0, total_eligible - len(jobs))}