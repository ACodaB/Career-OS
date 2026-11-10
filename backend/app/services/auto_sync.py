"""
Automatic job fetching.

A small background thread inside the backend that, on a schedule, calls your own
POST /jobs/sync (exactly what the old "Run Search" button did), then removes
postings that have been taken down (POST /jobs/closed/clean), and records when
it last ran and what changed. Settings live in backend/data/auto_sync.json and
are changed from the Jobs page.

It only runs while the backend is running. If the backend was off for a while,
the first fetch happens shortly after it starts.
"""
import json
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BACKEND_DIR / "data" / "auto_sync.json"
SELF_URL = "http://127.0.0.1:8000"  # change this if your backend runs on another port
MIN_INTERVAL_MINUTES = 30
START_DELAY_SECONDS = 20     # let the server finish starting before the first check
CHECK_EVERY_SECONDS = 30

_DEFAULTS = {
    "enabled": False,
    "interval_minutes": 360,
    "board_tokens": [],      # empty = use the companies from your .env (TARGET_COMPANIES)
    "extra_companies": [],   # companies you added by searching for their name
    "last_run": None,
    "last_added": None,
    "last_removed": None,
    "last_error": None,
}
_lock = threading.Lock()        # guards the config file
_busy_lock = threading.Lock()   # guards the _busy flag
_started = False
_busy = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load() -> dict:
    cfg = dict(_DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except Exception:
        pass
    return cfg


def _save(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _clean_tokens(tokens) -> list:
    out = []
    for t in tokens or []:
        t = (t or "").strip().lower()
        if t and t not in out:
            out.append(t)
    return out


def get_status() -> dict:
    cfg = load()
    next_run = None
    if cfg["enabled"] and cfg["last_run"]:
        try:
            nxt = datetime.fromisoformat(cfg["last_run"]) + timedelta(minutes=cfg["interval_minutes"])
            next_run = nxt.isoformat()
        except Exception:
            pass
    return {**cfg, "next_run": next_run, "busy": _busy}


def update_settings(enabled: bool, interval_minutes: int, board_tokens=None) -> dict:
    with _lock:
        cfg = load()
        cfg["enabled"] = bool(enabled)
        cfg["interval_minutes"] = max(int(interval_minutes), MIN_INTERVAL_MINUTES)
        if board_tokens is not None:
            cfg["board_tokens"] = _clean_tokens(board_tokens)
        _save(cfg)
    return get_status()


def _due(cfg: dict) -> bool:
    if not cfg["enabled"]:
        return False
    if not cfg["last_run"]:
        return True
    try:
        last = datetime.fromisoformat(cfg["last_run"])
    except Exception:
        return True
    return _now() >= last + timedelta(minutes=cfg["interval_minutes"])


def _post(path: str, body: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        f"{SELF_URL}{path}",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)

def fetch_company(token: str) -> int:
    """
    Fetch one company's Greenhouse board right now and remember it, so the schedule
    keeps it fresh from then on. Returns how many new jobs came in.
    """
    token = (token or "").strip().lower()
    result = _post("/jobs/sync", {"board_tokens": [token]}, 300)
    errors = (result.get("errors") or {}) if isinstance(result, dict) else {}
    if errors.get(token):
        raise RuntimeError(str(errors[token])[:200])
    with _lock:
        cfg = load()
        cfg["extra_companies"] = _clean_tokens((cfg.get("extra_companies") or []) + [token])
        _save(cfg)
    return int((result.get("total_inserted") or 0) if isinstance(result, dict) else 0)

def _try_begin() -> bool:
    global _busy
    with _busy_lock:
        if _busy:
            return False
        _busy = True
        return True


def _do_run() -> None:
    """One fetch + cleanup. The caller must already have claimed _busy."""
    global _busy
    try:
        cfg = load()
        added = removed = None
        problems = []

        try:  # 1) fetch new jobs
            tokens = cfg["board_tokens"]
            result = _post("/jobs/sync", {"board_tokens": tokens} if tokens else {}, 900)
            if isinstance(result, dict):
                added = result.get("total_inserted")
                if result.get("errors"):  # some companies failed, others worked
                    problems += [f"{k}: {v}" for k, v in list(result["errors"].items())[:3]]
            fetched_ok = True
        except Exception as e:
            fetched_ok = False
            problems.append(str(e))

        extras = cfg.get("extra_companies") or []
        if fetched_ok and extras:  # 1b) companies you added by searching their name
            try:
                r2 = _post("/jobs/sync", {"board_tokens": extras}, 900)
                if isinstance(r2, dict):
                    added = (added or 0) + (r2.get("total_inserted") or 0)
                    if r2.get("errors"):
                        problems += [f"{k}: {v}" for k, v in list(r2["errors"].items())[:3]]
            except Exception as e:
                problems.append(f"extra companies: {e}")
                
        if fetched_ok:  # 2) drop postings that were taken down
            try:
                removed = _post("/jobs/closed/clean", {}, 600).get("removed")
            except Exception as e:
                problems.append(f"closed-job cleanup: {e}")

        with _lock:
            cfg = load()  # re-read: you may have changed settings meanwhile
            cfg["last_run"] = _now().isoformat()
            cfg["last_added"] = added
            cfg["last_removed"] = removed
            cfg["last_error"] = "; ".join(problems)[:300] or None
            _save(cfg)
    finally:
        with _busy_lock:
            _busy = False


def run_once() -> None:
    if _try_begin():
        _do_run()


def run_in_background() -> dict:
    """Start a fetch right now (even if the schedule is off). Returns immediately."""
    if _try_begin():
        threading.Thread(target=_do_run, daemon=True, name="auto-sync-now").start()
    return get_status()


def _loop() -> None:
    time.sleep(START_DELAY_SECONDS)
    while True:
        try:
            if _due(load()):
                run_once()
        except Exception:
            pass
        time.sleep(CHECK_EVERY_SECONDS)


def start() -> None:
    """Start the background thread (safe to call more than once)."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="auto-sync").start()