"""
Find synced jobs that are no longer posted, using Greenhouse's public board API.

For each company we fetch the board's current list of open jobs and flag your
saved jobs whose Greenhouse id is no longer on it. We only judge a company when
its board loaded and returned jobs, so a network blip or a wrong board name
never flags anything. This module never deletes anything itself; the API layer
decides what to remove (see select_removable).
"""
import json
import re
import urllib.request

BOARD_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"

# Safety net for automatic cleanup: if nearly every saved job of a company looks
# closed, something is probably off (wrong board, partial response), so skip it.
SUSPICIOUS_MIN_JOBS = 10
SUSPICIOUS_RATIO = 0.9


def greenhouse_job_id(job):
    raw = job.raw_data if isinstance(job.raw_data, dict) else {}
    rid = raw.get("id")
    if rid is not None and re.fullmatch(r"\d{5,}", str(rid)):
        return str(rid)
    url = job.url or ""
    m = (
        re.search(r"[?&]gh_jid=(\d+)", url)
        or re.search(r"/jobs/(\d{5,})", url)
        or re.search(r"/job/(\d{5,})", url)
    )
    return m.group(1) if m else None


def _board_ids(token: str):
    """Set of open job ids on this board, or None if it couldn't be read."""
    req = urllib.request.Request(
        BOARD_URL.format(token=token), headers={"User-Agent": "career-os/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.load(resp)
    except Exception:
        return None
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        return None
    return {str(j.get("id")) for j in jobs}


def find_closed(jobs) -> dict:
    by_company: dict = {}
    for j in jobs:
        by_company.setdefault((j.company or "").strip().lower(), []).append(j)

    closed, unverified, stats = [], [], {}
    checked = no_id = 0
    for token, group in by_company.items():
        if not re.fullmatch(r"[a-z0-9_-]+", token or ""):
            unverified.append({"company": token or "(blank)", "reason": "not a usable board name"})
            continue
        open_ids = _board_ids(token)
        if open_ids is None:
            unverified.append({"company": token, "reason": "board could not be loaded"})
            continue
        if not open_ids:
            unverified.append({"company": token, "reason": "board returned no jobs"})
            continue
        n_checked = n_closed = 0
        for j in group:
            jid = greenhouse_job_id(j)
            if jid is None:
                no_id += 1
                continue
            n_checked += 1
            if jid not in open_ids:
                closed.append(j)
                n_closed += 1
        checked += n_checked
        stats[token] = {"checked": n_checked, "closed": n_closed}
    return {
        "closed": closed,
        "unverified": unverified,
        "checked": checked,
        "no_id": no_id,
        "stats": stats,
    }


def select_removable(result: dict, tracked_ids):
    """
    Decide what automatic cleanup may delete.
    Returns (to_remove, kept_tracked, skipped_companies).
    """
    tracked_ids = set(tracked_ids)
    to_remove, kept_tracked, skipped = [], [], []
    for j in result["closed"]:
        token = (j.company or "").strip().lower()
        st = result["stats"].get(token, {})
        if (
            st.get("checked", 0) >= SUSPICIOUS_MIN_JOBS
            and st["closed"] / st["checked"] >= SUSPICIOUS_RATIO
        ):
            if token not in skipped:
                skipped.append(token)
            continue
        (kept_tracked if j.id in tracked_ids else to_remove).append(j)
    return to_remove, kept_tracked, skipped