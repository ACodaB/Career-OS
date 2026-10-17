"""
SQLAlchemy models.
"""
from datetime import datetime, timezone
from sqlalchemy.orm import relationship, backref, Mapped, mapped_column
from sqlalchemy import String, Text, DateTime, JSON, ForeignKey

from app.db import Base


class UserProfile(Base):
    """Single-row table (single-user tool) holding your info + resume."""
    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(50), default="")
    work_authorization: Mapped[str] = mapped_column(String(200), default="")
    education: Mapped[str] = mapped_column(Text, default="")  # free text for now
    resume_text: Mapped[str] = mapped_column(Text, default="")  # full resume, pasted in
    skills: Mapped[str] = mapped_column(Text, default="")  # comma-separated for now
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now(timezone.utc))


class Job(Base):
    """A normalized job posting pulled from a job source."""
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(300))
    location: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    salary: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str] = mapped_column(String(1000), unique=True)  # used for dedupe
    source: Mapped[str] = mapped_column(String(100), default="")
    posted_at: Mapped[str] = mapped_column(String(100), default="")
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)  # keep raw payload for later reuse
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now(timezone.utc))

    # Match fields (filled in during Phase 2) — nullable until then
    match_percent: Mapped[int] = mapped_column(default=0)
    match_recommendation: Mapped[str] = mapped_column(String(50), default="")
    match_reasoning: Mapped[dict] = mapped_column(JSON, default=dict)
    
    # Application prep fields (filled in during Phase 3) — nullable until then
    tailored_resume: Mapped[str] = mapped_column(Text, default="")
    tailored_cover_letter: Mapped[str] = mapped_column(Text, default="")
    application_generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)

class Application(Base):
    __tablename__ = "applications"

    id : Mapped[int] = mapped_column(primary_key=True, index=True)
    job_id : Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    company : Mapped[str] = mapped_column(String(50),nullable=False)
    title : Mapped[str] = mapped_column(String(50),nullable=False)
    resume_snapshot : Mapped[str] = mapped_column(Text, nullable=False)
    cover_letter_snapshot : Mapped[str] = mapped_column(Text, nullable=False)
    status : Mapped[str] = mapped_column(String(15),nullable=False, default="Submitted")
    submitted_at : Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now(timezone.utc))
    updated_at : Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    job = relationship("Job", backref="applications")

class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id : Mapped[int] = mapped_column(primary_key=True, index=True)
    application_id : Mapped[int] = mapped_column(ForeignKey("applications.id"), nullable=False)
    interview_type : Mapped[str] = mapped_column(String(15), nullable=False)  # "behavioral" | "technical" | "resume"
    questions : Mapped[str] = mapped_column(Text, nullable=False)          # JSON-encoded list[str] from the prep call
    transcript : Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON-encoded list[{role, content}]
    evaluation : Mapped[str] = mapped_column(Text, nullable=True)          # JSON-encoded final eval, filled when status flips to completed
    status : Mapped[str] = mapped_column(String, nullable=False, default="in_progress")  # "in_progress" | "completed"
    created_at : Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now(timezone.utc))
    updated_at : Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now(timezone.utc),
                                                   onupdate=datetime.now(timezone.utc))

    application = relationship(
        "Application",
        backref=backref("interview_sessions", cascade="all, delete-orphan"),
    )
    