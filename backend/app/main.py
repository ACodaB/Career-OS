"""
Career OS backend entrypoint.

Run with:
    uvicorn app.main:app --reload
"""
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
import threading

from app.db import Base, engine, get_db
from app.models import UserProfile, Job
from app.config import settings
from app.services.job_sync import sync_greenhouse_companies
from app.services.matching import match_all_jobs
from app.services.application_prep import generate_application

# Creates tables on startup if they don't exist yet (fine for SQLite/dev;
# swap for a real migration tool like Alembic later if needed).
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Career OS", version="0.1.0")
_matching_lock = threading.Lock()

# Allow the local Vite dev server to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


# ---- Profile ----

class ProfileIn(BaseModel):
    name: str
    email: str
    phone: str = ""
    work_authorization: str = ""
    education: str = ""
    resume_text: str = ""
    skills: str = ""


@app.get("/profile")
def get_profile(db: Session = Depends(get_db)):
    profile = db.query(UserProfile).first()
    return profile


@app.post("/profile")
def upsert_profile(payload: ProfileIn, db: Session = Depends(get_db)):
    profile = db.query(UserProfile).first()
    if profile is None:
        profile = UserProfile(**payload.model_dump())
        db.add(profile)
    else:
        for k, v in payload.model_dump().items():
            setattr(profile, k, v)
    db.commit()
    db.refresh(profile)
    return profile


# ---- Jobs ----

@app.get("/jobs")
def list_jobs(limit: int | None = None, db: Session = Depends(get_db)):
    query = db.query(Job).order_by(Job.created_at.desc())
    if limit:
        query = query.limit(limit)
    return query.all()


class SyncJobsIn(BaseModel):
    # Optional override — if omitted, uses TARGET_COMPANIES from .env
    board_tokens: list[str] | None = None


@app.post("/jobs/sync")
def sync_jobs(payload: SyncJobsIn, db: Session = Depends(get_db)):
    tokens = payload.board_tokens or [
        t for t in settings.target_companies.split(",") if t.strip()
    ]
    if not tokens:
        return {
            "error": "No companies configured. Set TARGET_COMPANIES in .env "
                     "or pass board_tokens in the request body."
        }
    return sync_greenhouse_companies(db, tokens)


class MatchJobsIn(BaseModel):
    only_unmatched: bool = True
    limit: int | None = None
    companies: list[str] | None = None


@app.post("/jobs/match")
def run_matching(payload: MatchJobsIn = MatchJobsIn(), db: Session = Depends(get_db)):
    profile = db.query(UserProfile).first()
    if not profile:
        raise HTTPException(status_code=400, detail="No profile found. Create a profile first.")

    if not _matching_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A matching run is already in progress. Wait for it to finish.")

    try:
        result = match_all_jobs(
            db, profile,
            only_unmatched=payload.only_unmatched,
            limit=payload.limit,
            companies=payload.companies,
        )
        return result
    finally:
        _matching_lock.release()

@app.post("/jobs/{job_id}/generate-application")
def generate_application_endpoint(job_id: int, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    profile = db.query(UserProfile).first()
    if not profile:
        raise HTTPException(status_code=400, detail="No profile found. Create a profile first.")

    try:
        updated_job = generate_application(db, job, profile)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return updated_job

