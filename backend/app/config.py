"""
Central app configuration, loaded from environment variables / .env file.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    # Defaults to a local SQLite file so the app runs with zero extra setup.
    # Swap to a Postgres URL later if you want, e.g.:
    #   postgresql+psycopg2://user:password@localhost:5432/career_os
    database_url: str = "sqlite:///./career_os.db"

    # LLM + embeddings (Gemini covers both, so this is the only AI key you need)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_embedding_model: str = "text-embedding-004"

    # Vector store (Chroma persists to disk here)
    chroma_persist_dir: str = "./chroma_data"

    # Job sources — comma-separated Greenhouse board tokens, e.g. "stripe,notion,airbnb"
    # The token is the slug in a company's job board URL: boards.greenhouse.io/<token>
    target_companies: str = ""

    # App
    app_env: str = "dev"


settings = Settings()
