"""
SQLAlchemy engine/session setup. Works with SQLite (default) or Postgres
(just change DATABASE_URL in .env) without any code changes elsewhere.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: yields a DB session, always closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
