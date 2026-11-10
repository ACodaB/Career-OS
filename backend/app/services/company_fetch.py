"""
Search-by-company-name: if the search box holds a company we haven't fetched yet,
check whether that company has a Greenhouse board and, if so, fetch its jobs.

Kept deliberately cautious, because any single word you search could be a company:
  - only 1-2 word queries are considered,
  - nothing happens if you already have jobs from that company (or the query
    mentions one),
  - a board must exist and hold at most MAX_BOARD_JOBS jobs,
  - names that turn out not to exist are remembered for an hour (no repeat lookups).
"""
import re
import time

from app.services import auto_sync, closed_jobs

MAX_BOARD_JOBS = 1500
_NEG_TTL_SECONDS = 3600
_not_a_board: dict = {}


def candidate_tokens(query: str) -> list:
    words = re.findall(r"[a-z0-9]+", (query or "").lower())
    if not words or len(words) > 2:
        return []
    cands = ["".join(words)]
    if len(words) == 2:
        cands.append("-".join(words))
    return [c for c in cands if len(c) >= 2]


def maybe_fetch_company(query: str, known_companies) -> dict | None:
    """
    known_companies: lowercase company names you already have jobs for.
    Returns None (nothing to do) or {"token", "open_jobs", "added"} / {"token", "error"}.
    """
    known = set(known_companies)
    cands = candidate_tokens(query)
    words = set(re.findall(r"[a-z0-9]+", (query or "").lower()))
    if not cands or (set(cands) & known) or (words & known):
        return None

    for token in cands:
        if time.time() - _not_a_board.get(token, 0) < _NEG_TTL_SECONDS:
            continue
        ids = closed_jobs._board_ids(token)
        if not ids:
            _not_a_board[token] = time.time()
            continue
        if len(ids) > MAX_BOARD_JOBS:
            return {"token": token, "error": f"its board has {len(ids)} jobs, too many to fetch automatically"}
        try:
            added = auto_sync.fetch_company(token)
        except Exception as e:
            return {"token": token, "error": str(e)[:200]}
        return {"token": token, "open_jobs": len(ids), "added": added}
    return None