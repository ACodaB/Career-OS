"""
Takes normalized job dicts (from any source, e.g. app/ingestion/greenhouse.py)
and upserts them into the database, deduped by URL.
"""
from sqlalchemy.orm import Session

from app.models import Job
from app.ingestion.greenhouse import fetch_and_normalize


def upsert_jobs(db: Session, normalized_jobs: list[dict]) -> dict:
    """
    Inserts new jobs, skips ones we already have (matched by URL).
    Returns a summary dict: {"inserted": N, "skipped": N}.
    """
    inserted = 0
    skipped = 0

    for job_data in normalized_jobs:
        if not job_data.get("url"):
            skipped += 1
            continue

        exists = db.query(Job).filter(Job.url == job_data["url"]).first()
        if exists:
            skipped += 1
            continue

        db.add(Job(**job_data))
        inserted += 1

    db.commit()
    return {"inserted": inserted, "skipped": skipped}


def sync_greenhouse_companies(db: Session, board_tokens: list[str]) -> dict:
    """
    Fetches + normalizes + upserts jobs for a list of Greenhouse board tokens.
    Returns a per-company breakdown plus totals, so failures on one company
    (e.g. a typo'd token) don't block the others.
    """
    results = {}
    total_inserted = 0
    total_skipped = 0
    errors = {}

    for token in board_tokens:
        token = token.strip()
        if not token:
            continue
        try:
            normalized = fetch_and_normalize(token)
            summary = upsert_jobs(db, normalized)
            results[token] = summary
            total_inserted += summary["inserted"]
            total_skipped += summary["skipped"]
        except Exception as e:
            errors[token] = str(e)

    return {
        "total_inserted": total_inserted,
        "total_skipped": total_skipped,
        "by_company": results,
        "errors": errors,
    }
