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
import json

from app.db import Base, engine, get_db
from app.models import UserProfile, Job, Application, InterviewSession
from app.config import settings
from app.services.job_sync import sync_greenhouse_companies
from app.services.matching import match_all_jobs
from app.services.application_prep import generate_application
from app.services.interview_prep import (
    generate_questions, VALID_TYPES, get_state, process_answer,
    finish_session, start_question, skip_question,
)

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
        existing.updated_at = datetime.now(timezone.utc)
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
        submitted_at=datetime.now(timezone.utc),
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


class InterviewPrepRequest(BaseModel):
    interview_type: str  # "behavioral" | "technical" | "resume"

# ---Interview-prep---
@app.post("/applications/{application_id}/interview-prep")
def interview_prep(application_id: int, body: InterviewPrepRequest, db: Session = Depends(get_db)):
    if body.interview_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"interview_type must be one of {sorted(VALID_TYPES)}")

    application = db.query(Application).filter(Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    existing = (
    db.query(InterviewSession)
    .filter(
        InterviewSession.application_id == application.id,
        InterviewSession.interview_type == body.interview_type,
        InterviewSession.status == "in_progress",
    )
    .order_by(InterviewSession.updated_at.desc())
    .first()
    )
    if existing:
        return {
            "session_id": existing.id,
            "interview_type": existing.interview_type,
            "questions": json.loads(existing.questions),
            "reused": True,
        }

    try:
        questions = generate_questions(application.job, application.resume_snapshot, body.interview_type)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Question generation failed: {e}")

    session = InterviewSession(
        application_id=application.id,
        interview_type=body.interview_type,
        questions=json.dumps(questions),
        transcript="[]",
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return {"session_id": session.id, "interview_type": session.interview_type, "questions": questions}

class AnswerRequest(BaseModel):
    answer: str


@app.get("/interview-sessions/{session_id}")
def get_interview_session(session_id: int, db: Session = Depends(get_db)):
    session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")
    return get_state(session)



@app.post("/interview-sessions/{session_id}/finish")
def finish_interview_session(session_id: int, db: Session = Depends(get_db)):
    session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")

    try:
        evaluation = finish_session(session, session.application.job)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Final evaluation failed: {e}")

    db.commit()
    return evaluation


class QuestionPick(BaseModel):
    question_index: int


def _get_session_or_404(db: Session, session_id: int) -> InterviewSession:
    session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")
    return session


@app.get("/interview-sessions")
def list_interview_sessions(db: Session = Depends(get_db)):
    sessions = db.query(InterviewSession).order_by(InterviewSession.updated_at.desc()).all()
    out = []
    for s in sessions:
        if not s.application:  # application was undone/deleted; hide orphaned sessions
            continue
        state = get_state(s)
        out.append({
            "session_id": s.id,
            "application_id": s.application_id,
            "company": s.application.company,
            "title": s.application.title,
            "interview_type": s.interview_type,
            "status": s.status,
            "answered_count": state["answered_count"],
            "total_questions": state["total_questions"],
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        })
    return out


@app.post("/interview-sessions/{session_id}/start-question")
def start_interview_question(session_id: int, body: QuestionPick, db: Session = Depends(get_db)):
    session = _get_session_or_404(db, session_id)
    if session.status == "completed":
        raise HTTPException(status_code=409, detail="This session is completed")
    try:
        state = start_question(session, body.question_index)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    return state


@app.post("/interview-sessions/{session_id}/skip-question")
def skip_interview_question(session_id: int, body: QuestionPick, db: Session = Depends(get_db)):
    session = _get_session_or_404(db, session_id)
    if session.status == "completed":
        raise HTTPException(status_code=409, detail="This session is completed")
    try:
        state = skip_question(session, body.question_index)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    return state


@app.post("/interview-sessions/{session_id}/answer")
def answer_interview_question(session_id: int, body: AnswerRequest, db: Session = Depends(get_db)):
    if not body.answer.strip():
        raise HTTPException(status_code=400, detail="Answer cannot be empty")

    session = _get_session_or_404(db, session_id)
    if session.status == "completed":
        raise HTTPException(status_code=409, detail="This session is completed")
    if get_state(session)["active_question_index"] is None:
        raise HTTPException(status_code=409, detail="No active question. Pick a question first.")

    application = session.application
    try:
        result = process_answer(session, application.job, application.resume_snapshot, body.answer.strip())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Evaluation failed: {e}")

    db.commit()
    return result

@app.delete("/interview-sessions/{session_id}")
def delete_interview_session(session_id: int, db: Session = Depends(get_db)):
    session = _get_session_or_404(db, session_id)
    db.delete(session)
    db.commit()
    return {"deleted": True}