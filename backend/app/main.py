"""
Career OS backend entrypoint.

Run with:
    uvicorn app.main:app --reload
"""
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime, timezone
import threading

from app.db import Base, engine, get_db
from app.models import UserProfile, Job, Application
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

class SubmitApplicationRequest(BaseModel):
    tailored_resume: str
    tailored_cover_letter: str


class UpdateApplicationStatusRequest(BaseModel):
    status: str


VALID_APPLICATION_STATUSES = {"Submitted", "OA Pending", "Interview", "Rejected"}


@app.post("/jobs/{job_id}/submit-application")
def submit_application(job_id: int, payload: SubmitApplicationRequest, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    existing = db.query(Application).filter(Application.job_id == job_id).first()

    if existing:
        # Resubmitting the same job updates the existing tracked record
        # instead of creating a duplicate. Status is intentionally left
        # as-is (don't reset progress like "Interview" back to "Submitted"
        # just because the resume text was re-saved).
        existing.resume_snapshot = payload.tailored_resume
        existing.cover_letter_snapshot = payload.tailored_cover_letter
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    application = Application(
        job_id=job.id,
        company=job.company,
        title=job.title,
        resume_snapshot=payload.tailored_resume,
        cover_letter_snapshot=payload.tailored_cover_letter,
        status="Submitted",
        submitted_at=datetime.utcnow(),
    )
    db.add(application)
    db.commit()
    db.refresh(application)
    return application


@app.get("/applications")
def list_applications(db: Session = Depends(get_db)):
    return db.query(Application).order_by(Application.submitted_at.desc()).all()


@app.patch("/applications/{application_id}/status")
def update_application_status(
    application_id: int, payload: UpdateApplicationStatusRequest, db: Session = Depends(get_db)
):
    if payload.status not in VALID_APPLICATION_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {sorted(VALID_APPLICATION_STATUSES)}",
        )

    application = db.query(Application).filter(Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    application.status = payload.status
    application.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(application)
    return application

@app.delete("/applications/{application_id}")
def delete_application(application_id: int, db: Session = Depends(get_db)):
    application = db.query(Application).filter(Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    db.delete(application)
    db.commit()
    return {"deleted": True, "id": application_id}
