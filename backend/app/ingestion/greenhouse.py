"""
Greenhouse job board ingestion.

Greenhouse exposes a public, unauthenticated JSON API per company:
    https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true

`board_token` is the slug in the company's public job board URL, e.g. for
boards.greenhouse.io/stripe the token is "stripe".

This module is split into two layers on purpose:
  - `fetch_raw_jobs()`      — the only function that touches the network.
  - `normalize_job()`       — pure function, no network, easy to unit test.
This keeps the "does the API shape parse correctly" logic testable even
without live network access.
"""
import re

import httpx
from bs4 import BeautifulSoup

GREENHOUSE_BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"


def fetch_raw_jobs(board_token: str) -> list[dict]:
    """Hits the Greenhouse API for one company and returns the raw job list."""
    url = GREENHOUSE_BASE_URL.format(board_token=board_token)
    response = httpx.get(url, params={"content": "true"}, timeout=15)
    response.raise_for_status()
    data = response.json()
    return data.get("jobs", [])


def _strip_html(html: str) -> str:
    """Greenhouse job descriptions come as HTML — convert to clean plain text."""
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(separator="\n")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def normalize_job(raw: dict, board_token: str) -> dict:
    """
    Converts one raw Greenhouse job record into the shape our `Job` model
    expects (see app/models.py). Pure function — no network calls — so it
    can be unit tested directly against sample API payloads.
    """
    location = (raw.get("location") or {}).get("name", "")
    return {
        "company": board_token,  # Greenhouse doesn't return a display name here; board_token is the identifier
        "title": raw.get("title", "").strip(),
        "location": location,
        "description": _strip_html(raw.get("content", "")),
        "salary": "",  # Greenhouse doesn't expose salary in this endpoint
        "url": raw.get("absolute_url", ""),
        "source": "greenhouse",
        "posted_at": raw.get("updated_at", ""),
        "raw_data": raw,
    }


def fetch_and_normalize(board_token: str) -> list[dict]:
    """Convenience wrapper: fetch + normalize in one call for a single company."""
    raw_jobs = fetch_raw_jobs(board_token)
    return [normalize_job(job, board_token) for job in raw_jobs]
