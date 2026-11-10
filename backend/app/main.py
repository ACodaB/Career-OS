"""
Career OS backend entrypoint.

Run with:
    uvicorn app.main:app --reload
"""
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session,load_only
from pydantic import BaseModel
from datetime import datetime, timezone
import threading
import json,subprocess,sys,time
from pathlib import Path
from fastapi.responses import JSONResponse
import uuid



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
from app.services.essay_answers import draft_essay_answers

from app.services.documents import build_cover_letter_pdf, build_resume_pdf

from app.services import closed_jobs, job_search,auto_sync,company_fetch

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
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Generation failed: {e}")

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
        existing.resume_snapshot = payload.tailored_resume or job.tailored_resume or ""
        existing.cover_letter_snapshot = payload.tailored_cover_letter or job.tailored_cover_letter or ""
        existing.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing)
        return existing

    application = Application(
        job_id=job.id,
        company=job.company,
        title=job.title,
        resume_snapshot=payload.tailored_resume or job.tailored_resume or "",
        cover_letter_snapshot=payload.tailored_cover_letter or job.tailored_cover_letter or "",
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

# ---------------------------------------------------------------------------
# Phase 6 — Auto-fill (Playwright runner is launched as a separate process)
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data"
AUTOFILL_DIR = DATA_DIR / "autofill"
AUTOFILL_DIR.mkdir(parents=True, exist_ok=True)
AUTOFILL_DEFAULTS_PATH = DATA_DIR / "autofill_defaults.json"


class DraftEssaysBody(BaseModel):
    questions: list[str]

class LaunchAutofillBody(BaseModel):
    essay_answers: dict[str, str] = {}
    resume_text: str | None = None        # your edited text from the app, if any
    cover_letter_text: str | None = None


def _load_autofill_defaults() -> dict:
    if not AUTOFILL_DEFAULTS_PATH.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Missing {AUTOFILL_DEFAULTS_PATH}. Create it first.",
        )
    return json.loads(AUTOFILL_DEFAULTS_PATH.read_text(encoding="utf-8"))


def _get_job_and_profile(db: Session, job_id: int):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    profile = db.query(UserProfile).first()
    if not profile:
        raise HTTPException(status_code=400, detail="No profile found. Create a profile first.")
    return job, profile

_EXTRA_KEYS = (
    "country", "city", "zip", "employer", "job_title", "start_month", "start_year",
    "end_month", "end_year", "school", "degree", "discipline",
)

def _build_autofill_payload(
    job,
    profile,
    mode: str,
    report_path: Path,
    essay_answers=None,
    with_documents: bool = False,
    resume_text=None,
    cover_letter_text=None,
) -> dict:
    defaults = _load_autofill_defaults()
    parts = (profile.name or "").strip().split(" ", 1)

    resume_src = resume_text or job.tailored_resume or ""
    cover_src = cover_letter_text or job.tailored_cover_letter or ""

    resume_pdf = defaults.get("resume_pdf_path", "")  # fallback: your base resume PDF
    cover_pdf = ""
    notes = {}
    if with_documents:
        if resume_src.strip():
            try:
                resume_pdf = str(build_resume_pdf(job, profile, resume_src))
                notes["resume"] = "tailored PDF for this job"
            except Exception as e:
                notes["resume"] = f"base resume PDF (tailored one failed: {str(e)[:200]})"
        else:
            notes["resume"] = "base resume PDF (no tailored resume yet)"

        if cover_src.strip():
            try:
                cover_pdf = str(build_cover_letter_pdf(job, profile, cover_src))
                notes["cover_letter"] = "tailored PDF for this job"
            except Exception as e:
                notes["cover_letter"] = f"pasted as text (PDF failed: {str(e)[:200]})"
        else:
            notes["cover_letter"] = "none (no cover letter yet)"

    return {
        "mode": mode,
        "url": job.url,
        "board_token": (job.company or "").strip().lower(),
        "first_name": parts[0] if parts else "",
        "last_name": parts[1] if len(parts) > 1 else "",
        "email": profile.email,
        "phone": profile.phone,
        "linkedin": defaults.get("linkedin", ""),
        "github": defaults.get("github", ""),
        "website": defaults.get("website", ""),
        "resume_pdf_path": resume_pdf,
        "cover_letter_text": cover_src,
        "cover_letter_pdf_path": cover_pdf,
        "essay_answers": essay_answers or {},
        "extras": {k: defaults[k] for k in _EXTRA_KEYS if defaults.get(k)},
        "report_path": str(report_path),
        "_doc_notes": notes,
    }


def _write_payload(job_id: int, mode: str, payload: dict) -> Path:
    payload_path = AUTOFILL_DIR / f"job{job_id}_{mode}_{uuid.uuid4().hex[:8]}.json"
    payload_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload_path

def _runner_cmd(payload_path: Path) -> list[str]:
    return [sys.executable, "-u", "-m", "app.services.autofill_runner", str(payload_path)]

def _handle_closed_job(db: Session, job, reason: str):
    """
    A posting is gone. Remove it from the jobs list unless it's tracked as an
    application. Returns a 410 the frontend uses to drop the card.
    """
    job_id, title = job.id, job.title  # read before deleting
    tracked = db.query(Application).filter(Application.job_id == job_id).first() is not None
    removed = False
    if not tracked:
        db.delete(job)
        db.commit()
        removed = True
    msg = f'"{title}" is no longer available ({reason}).'
    msg += (
        " It was removed from your jobs list."
        if removed
        else " It's kept because it's tracked in your Applications."
    )
    return JSONResponse(
        status_code=410, content={"detail": msg, "job_removed": removed, "job_id": job_id}
    )


@app.post("/jobs/{job_id}/autofill/scan")
def autofill_scan(job_id: int, db: Session = Depends(get_db)):
    """Headless scan of the application form -> required essay questions."""
    job, profile = _get_job_and_profile(db, job_id)
    report_path = AUTOFILL_DIR / f"job{job_id}_scan_{uuid.uuid4().hex[:8]}_report.json"

    payload = _build_autofill_payload(job, profile, "scan", report_path)
    payload_path = _write_payload(job_id, "scan", payload)

    try:
        proc = subprocess.run(
            _runner_cmd(payload_path),
            cwd=str(BACKEND_DIR),
            capture_output=True,
            text=True,
            timeout=90,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Scanning the form timed out.")

    if not report_path.exists():
        out = (proc.stdout or "").strip()[-1500:]
        err = (proc.stderr or "").strip()[-800:]
        raise HTTPException(
            status_code=502,
            detail=f"Scan failed (exit code {proc.returncode}).\n{err or out or 'The runner printed nothing.'}",
        )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    payload_path.unlink(missing_ok=True)
    report_path.unlink(missing_ok=True)
    if report.get("error"):
        raise HTTPException(status_code=502, detail=f"Scan failed:\n{report['error']}")
    if report.get("job_closed"):
        return _handle_closed_job(db, job, report.get("closed_reason", "closed"))
    if report.get("form_found") is False:
        raise HTTPException(
            status_code=422,
            detail=f"No application form found at {report.get('final_url')}.",
        )
    
    # Make sure this job has its tailored resume + cover letter (they become the uploaded PDFs)
    generated, gen_error = False, None
    if not (job.tailored_resume or "").strip() or not (job.tailored_cover_letter or "").strip():
        try:
            generate_application(db, job, profile)
            generated = True
        except Exception as e:
            db.rollback()
            gen_error = str(e)[:200]

    return {
        "job_id": job_id,
        "url": report.get("url"),
        "essay_questions": report.get("essay_questions", []),
        "application_generated": generated,
        "application_error": gen_error,
    }


@app.post("/jobs/{job_id}/autofill/draft-essays")
def autofill_draft_essays(job_id: int, body: DraftEssaysBody, db: Session = Depends(get_db)):
    """LLM drafts for the given essay questions. Nothing is saved."""
    job, profile = _get_job_and_profile(db, job_id)
    questions = [q.strip() for q in body.questions if q.strip()]
    if not questions:
        raise HTTPException(status_code=400, detail="No questions provided.")
    try:
        drafts = draft_essay_answers(job, profile, questions)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Drafting failed: {e}")
    return {"job_id": job_id, "drafts": drafts}


@app.post("/jobs/{job_id}/autofill/launch")
def autofill_launch(job_id: int, body: LaunchAutofillBody, db: Session = Depends(get_db)):
    """
    Opens a visible Chrome window, fills the form (including approved essay
    answers), and leaves it open for you. NEVER submits.
    """
    job, profile = _get_job_and_profile(db, job_id)
    report_path = AUTOFILL_DIR / f"job{job_id}_fill_report.json"
    report_path.unlink(missing_ok=True)

    payload = _build_autofill_payload(
        job,
        profile,
        "fill",
        report_path,
        body.essay_answers,
        with_documents=True,
        resume_text=body.resume_text,
        cover_letter_text=body.cover_letter_text,
    )
    payload_path = _write_payload(job_id, "fill", payload)

    log_path = AUTOFILL_DIR / f"job{job_id}_fill.log"
    log_file = open(log_path, "w", encoding="utf-8")
    subprocess.Popen(
        _runner_cmd(payload_path),
        cwd=str(BACKEND_DIR),
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    # The runner writes its report once filling is done, then keeps the
    # browser open. Wait up to 60s for the report to appear.
    report = None
    for _ in range(60):
        time.sleep(1)
        if report_path.exists():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
                break
            except json.JSONDecodeError:
                continue  # file still being written

    if report and report.get("job_closed"):
        return _handle_closed_job(db, job, report.get("closed_reason", "closed"))            
    return {
        "launched": True,
        "documents": payload.get("_doc_notes", {}),
        "report": report,
        "note": None if report else f"No report yet; check {log_path}",
    }

@app.post("/jobs/{job_id}/documents")
def make_documents(job_id: int, db: Session = Depends(get_db)):
    """Render this job's tailored resume + cover letter PDFs into its folder."""
    job, profile = _get_job_and_profile(db, job_id)
    files, errors = {}, {}
    for name, build in (("resume_pdf", build_resume_pdf), ("cover_letter_pdf", build_cover_letter_pdf)):
        try:
            files[name] = str(build(job, profile))
        except Exception as e:
            errors[name] = str(e)
    if not files:
        raise HTTPException(status_code=400, detail=" | ".join(errors.values()))
    return {"job_id": job_id, "files": files, "errors": errors}

# ---------------------------------------------------------------------------
# Keyword search + closed-posting cleanup
# ---------------------------------------------------------------------------
class JobSearchBody(BaseModel):
    query: str
    limit: int = 300


class RemoveJobsBody(BaseModel):
    job_ids: list[int]


def _search_rows(db: Session):
    return (
        db.query(Job)
        .options(load_only(Job.id, Job.title, Job.company, Job.location, Job.description))
        .all()
    )


@app.post("/jobs/search")
def search_jobs(body: JobSearchBody, db: Session = Depends(get_db)):
    q = (body.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Type a keyword or company name to search for.")

    # A company name we haven't fetched yet? Fetch its jobs first.
    known = {(c or "").strip().lower() for (c,) in db.query(Job.company).distinct().all()}
    fetched = company_fetch.maybe_fetch_company(q, known)
    if fetched:
        db.commit()  # end the old read snapshot so the new jobs are visible

    result = job_search.run_search(_search_rows(db), q, body.limit)
    result["fetched_company"] = fetched
    return result


@app.get("/jobs/search/status")
def search_index_status(db: Session = Depends(get_db)):
    return job_search.status([r[0] for r in db.query(Job.id).all()])


@app.post("/jobs/search/index")
def search_rebuild_index(db: Session = Depends(get_db)):
    """Retry building the semantic index (e.g. after a Gemini error)."""
    return job_search.start_indexing(_search_rows(db), force=True)


@app.post("/jobs/closed/check")
def check_closed_jobs(db: Session = Depends(get_db)):
    """Dry run: which saved jobs are no longer on their Greenhouse board? Deletes nothing."""
    result = closed_jobs.find_closed(db.query(Job).all())
    tracked = {r[0] for r in db.query(Application.job_id).all()}
    return {
        "checked": result["checked"],
        "closed": [
            {"id": j.id, "title": j.title, "company": j.company, "tracked": j.id in tracked}
            for j in result["closed"]
        ],
        "unverified": result["unverified"],
    }


@app.post("/jobs/closed/remove")
def remove_closed_jobs(body: RemoveJobsBody, db: Session = Depends(get_db)):
    """Delete the given jobs, except any that are tracked in Applications."""
    tracked = {r[0] for r in db.query(Application.job_id).all()}
    removed = kept = 0
    for job in db.query(Job).filter(Job.id.in_(body.job_ids)).all():
        if job.id in tracked:
            kept += 1
            continue
        db.delete(job)
        removed += 1
    db.commit()
    return {"removed": removed, "kept_tracked": kept}

# ---------------------------------------------------------------------------
# Automatic job fetching
# ---------------------------------------------------------------------------
class AutoSyncBody(BaseModel):
    enabled: bool
    interval_minutes: int = 360
    board_tokens: list[str] = []


@app.get("/auto-sync")
def auto_sync_status():
    return auto_sync.get_status()


@app.post("/auto-sync")
def auto_sync_save(body: AutoSyncBody):
    return auto_sync.update_settings(body.enabled, body.interval_minutes, body.board_tokens)

@app.post("/auto-sync/run")
def auto_sync_run_now():
    """Fetch new jobs right now (also removes closed postings). Returns immediately."""
    return auto_sync.run_in_background()


@app.post("/jobs/closed/clean")
def clean_closed_jobs(db: Session = Depends(get_db)):
    """Find postings that were taken down and delete them (never jobs tracked in Applications)."""
    result = closed_jobs.find_closed(db.query(Job).all())
    tracked = {r[0] for r in db.query(Application.job_id).all()}
    to_remove, kept_tracked, skipped = closed_jobs.select_removable(result, tracked)
    for job in to_remove:
        db.delete(job)
    db.commit()
    return {
        "removed": len(to_remove),
        "kept_tracked": len(kept_tracked),
        "skipped_companies": skipped,
        "checked": result["checked"],
    }


auto_sync.start()  # starts the background thread when the backend starts