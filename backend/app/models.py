"""
SQLAlchemy models. Starting with just what Phase 1 (profile + job search)
needs. More tables (Match, Application, Preference, CompanyBrief,
InterviewSession) get added in later phases per the implementation plan.
"""
from datetime import datetime

from sqlalchemy import String, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Match fields (filled in during Phase 2) — nullable until then
    match_percent: Mapped[int] = mapped_column(default=0)
    match_recommendation: Mapped[str] = mapped_column(String(50), default="")
    match_reasoning: Mapped[dict] = mapped_column(JSON, default=dict)
    
    # Application prep fields (filled in during Phase 3) — nullable until then
    tailored_resume: Mapped[str] = mapped_column(Text, default="")
    tailored_cover_letter: Mapped[str] = mapped_column(Text, default="")
    application_generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
