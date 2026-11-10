"""
Keyword search across ALL synced jobs: syntactic + semantic.

- Syntactic: which of your words appear in the title (strongest), company /
  location, and description (more mentions = stronger). Plurals and endings
  are handled (engineer / engineers / engineering).
- Semantic: embeddings (Gemini, same model as matching) so "ML engineer" also
  finds "machine learning scientist". Job vectors live in a small local index
  (backend/data/search_index) that is built in the background and only embeds
  new or changed jobs. Until a job is indexed it is ranked on keywords alone.

Nothing here touches the database except reading the job rows it is handed.
"""
import hashlib
import html as _html
import json
import re
import threading
import time
from pathlib import Path

import numpy as np

from app.llm import embed_text, embed_texts

BACKEND_DIR = Path(__file__).resolve().parents[2]
INDEX_DIR = BACKEND_DIR / "data" / "search_index"
VEC_PATH = INDEX_DIR / "vectors.npy"
META_PATH = INDEX_DIR / "meta.json"

# Tunable knobs
SYN_MIN = 0.30        # keyword score needed to count as a keyword hit (0..1)
SEM_MIN = 0.60        # semantic closeness needed to count as relevant (0..1)
W_SYN, W_SEM = 0.6, 0.4
EMBED_BATCH = 50
DOC_CHARS = 1500      # how much of each description is embedded
DESC_SCAN_CHARS = 20000

_STOP = {
    "a", "an", "and", "or", "the", "of", "for", "in", "at", "to", "with", "on",
    "job", "jobs", "role", "roles", "position", "positions", "opening", "openings",
}

_lock = threading.Lock()
_index = {"loaded": False, "ids": [], "hashes": [], "vecs": None}
_status = {"running": False, "done": 0, "todo": 0, "error": None}
_query_cache: dict = {}
_prep_cache: dict = {}


# ------------------------------------------------------------------ text ----
def _clean(raw: str) -> str:
    t = _html.unescape(raw or "")
    t = re.sub(r"<[^>]+>", " ", t)
    t = _html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def _prep(job) -> dict:
    key = (job.id, job.title, hash(job.description or ""), hash(job.location or ""))
    hit = _prep_cache.get(key)
    if hit:
        return hit
    desc = _clean(job.description)
    doc_text = f"{job.title} | {job.company} | {job.location}\n{desc[:DOC_CHARS]}"
    d = {
        "title": (job.title or "").lower(),
        "company": (job.company or "").lower(),
        "loc": (job.location or "").lower(),
        "desc": desc[:DESC_SCAN_CHARS].lower(),
        "doc_text": doc_text,
        "hash": hashlib.md5(doc_text.encode("utf-8")).hexdigest()[:12],
    }
    _prep_cache[key] = d
    return d


# ------------------------------------------------------------- syntactic ----
def _tokens(query: str) -> list[str]:
    raw = [t.strip(".-") for t in re.findall(r"[a-z0-9][a-z0-9+#.\-]*", query.lower())]
    raw = [t for t in raw if t]
    kept = [t for t in raw if t not in _STOP]
    return kept or raw


def _token_re(tok: str):
    esc = re.escape(tok)
    if len(tok) <= 3 or re.search(r"[+#.]", tok):  # short / symbolic: exact word only
        return re.compile(rf"(?<![a-z0-9]){esc}(?![a-z0-9])")
    stem = tok
    if len(stem) > 5 and stem.endswith("ing"):
        stem = stem[:-3]
    elif len(stem) > 4 and stem.endswith("ies"):
        stem = stem[:-3]
    elif len(stem) > 3 and stem.endswith("s") and not stem.endswith("ss"):
        stem = stem[:-1]
    return re.compile(rf"(?<![a-z0-9]){re.escape(stem)}[a-z0-9]*")


def _syntactic(doc: dict, patterns, phrase: str) -> float:
    if not patterns:
        return 0.0
    total = 0.0
    for rx in patterns:
        if rx.search(doc["title"]):
            s = 1.0
        else:
            s = 0.5 if (rx.search(doc["company"]) or rx.search(doc["loc"])) else 0.0
            c = len(rx.findall(doc["desc"]))
            if c:
                s = max(s, 0.25 + 0.1 * min(c, 5))
        total += s
    syn = total / len(patterns)
    if len(patterns) > 1:
        if phrase in doc["title"]:
            syn += 0.2
        elif phrase in doc["desc"]:
            syn += 0.05
    return min(syn, 1.0)


# ---------------------------------------------------------------- index -----
def _normalize(a: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(a, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return a / n


def _load() -> None:
    """Call with _lock held (or before any thread starts)."""
    if _index["loaded"]:
        return
    if VEC_PATH.exists() and META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text(encoding="utf-8"))
            vecs = np.load(VEC_PATH)
            if len(meta["ids"]) == len(vecs):
                _index.update(ids=meta["ids"], hashes=meta["hashes"], vecs=vecs)
        except Exception:
            pass
    _index["loaded"] = True


def _save() -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    if _index["vecs"] is not None:
        np.save(VEC_PATH, _index["vecs"])
    META_PATH.write_text(
        json.dumps({"ids": _index["ids"], "hashes": _index["hashes"]}), encoding="utf-8"
    )


def _add(chunk, vecs) -> None:
    ids, hashes, M = _index["ids"], _index["hashes"], _index["vecs"]
    new_ids = {c[0] for c in chunk}
    if M is not None and len(ids):
        keep = [k for k, i in enumerate(ids) if i not in new_ids]
        ids = [ids[k] for k in keep]
        hashes = [hashes[k] for k in keep]
        M = M[keep]
    else:
        ids, hashes, M = [], [], None
    arr = _normalize(np.asarray(vecs, dtype=np.float32))
    M = arr if (M is None or len(M) == 0) else np.vstack([M, arr])
    ids = ids + [c[0] for c in chunk]
    hashes = hashes + [c[2] for c in chunk]
    _index.update(ids=ids, hashes=hashes, vecs=M)


def _prune(live_ids: set) -> None:
    ids, hashes, M = _index["ids"], _index["hashes"], _index["vecs"]
    if M is None or not len(ids):
        return
    keep = [k for k, i in enumerate(ids) if i in live_ids]
    if len(keep) == len(ids):
        return
    _index.update(
        ids=[ids[k] for k in keep], hashes=[hashes[k] for k in keep], vecs=M[keep]
    )


def _embed_batch(texts: list[str]):
    backoff = 3.0
    for attempt in range(1, 6):
        try:
            return embed_texts(texts)
        except Exception as e:
            low = str(e).lower()
            rate = "429" in low or "rate" in low or "resource_exhausted" in low or "quota" in low
            if not rate or attempt == 5:
                raise
            time.sleep(backoff)
            backoff *= 2


def _worker(items, live_ids: set) -> None:
    try:
        for i in range(0, len(items), EMBED_BATCH):
            chunk = items[i : i + EMBED_BATCH]
            vecs = _embed_batch([c[1] for c in chunk])
            with _lock:
                _load()
                _add(chunk, vecs)
                _save()
            _status["done"] = min(i + EMBED_BATCH, len(items))
            time.sleep(0.5)
        with _lock:
            _prune(live_ids)
            _save()
    except Exception as e:
        _status["error"] = str(e)[:300]
    finally:
        _status["running"] = False


def _missing(jobs) -> list:
    with _lock:
        _load()
        have = dict(zip(_index["ids"], _index["hashes"]))
    out = []
    for j in jobs:
        d = _prep(j)
        if have.get(j.id) != d["hash"]:
            out.append((j.id, d["doc_text"], d["hash"]))
    return out


def start_indexing(jobs, force: bool = False) -> dict:
    """Start the background index build if anything is missing. Safe to call often."""
    if _status["running"]:
        return status([j.id for j in jobs])
    if force:
        _status["error"] = None
    items = _missing(jobs)
    if items and not _status["error"]:
        _status.update(running=True, done=0, todo=len(items), error=None)
        threading.Thread(
            target=_worker, args=(items, {j.id for j in jobs}), daemon=True
        ).start()
    return status([j.id for j in jobs])


def status(live_ids) -> dict:
    live = set(live_ids)
    with _lock:
        _load()
        indexed = sum(1 for i in _index["ids"] if i in live)
    return {
        "indexed": indexed,
        "total": len(live),
        "running": _status["running"],
        "done": _status["done"],
        "todo": _status["todo"],
        "error": _status["error"],
    }


# -------------------------------------------------------------- semantic ----
def _query_vec(query: str) -> np.ndarray:
    v = _query_cache.get(query)
    if v is None:
        v = _normalize(np.asarray([embed_text(query)], dtype=np.float32))[0]
        if len(_query_cache) > 50:
            _query_cache.clear()
        _query_cache[query] = v
    return v


def _semantic(query: str) -> dict:
    """{job_id: closeness 0..1}, relative to how the query scores across your jobs."""
    with _lock:
        _load()
        ids = list(_index["ids"])
        M = _index["vecs"]
    if M is None or not len(ids):
        return {}
    sims = M @ _query_vec(query)
    base = float(np.median(sims))
    span = max(float(sims.max()) - base, 1e-6)
    return {
        jid: float(min(max((float(s) - base) / span, 0.0), 1.0)) for jid, s in zip(ids, sims)
    }


# ---------------------------------------------------------------- search ----
def _company_query(query: str, jobs):
    """
    If the whole query is just a company name we have jobs for ("stripe", "door dash"),
    return that company's name (as stored), else None.
    """
    words = re.findall(r"[a-z0-9]+", (query or "").lower())
    if not words or len(words) > 2:
        return None
    wanted = {"".join(words), "-".join(words)}
    for j in jobs:
        c = (j.company or "").strip().lower()
        if c in wanted:
            return c
    return None


def run_search(jobs, query: str, limit: int = 300) -> dict:
    query = " ".join((query or "").split())

    # A company name: list that company's jobs. They all match the query equally, so the
    # page orders them by how well they match your resume.
    company = _company_query(query, jobs)
    if company:
        results = [
            {"job_id": j.id, "relevance": 100.0, "syntactic": 1.0, "semantic": None}
            for j in jobs
            if (j.company or "").strip().lower() == company
        ]
        info = start_indexing(jobs)
        return {
            "query": query,
            "company": company,
            "total_matches": len(results),
            "results": results[:limit],
            "semantic": {
                "indexed": info["indexed"],
                "total": info["total"],
                "indexing": info["running"],
                "error": info["error"],
            },
        }

    toks = _tokens(query)
    patterns = [_token_re(t) for t in toks]
    phrase = " ".join(toks)

    sem, sem_error = {}, None
    try:
        sem = _semantic(query)
    except Exception as e:
        sem_error = str(e)[:200]

    results = []
    for j in jobs:
        doc = _prep(j)
        syn = _syntactic(doc, patterns, phrase)
        s = sem.get(j.id)
        if not (syn >= SYN_MIN or (s is not None and s >= SEM_MIN)):
            continue
        rel = 100 * (W_SYN * syn + W_SEM * s) if s is not None else 100 * syn * 0.9
        results.append(
            {
                "job_id": j.id,
                "relevance": round(rel, 1),
                "syntactic": round(syn, 2),
                "semantic": None if s is None else round(s, 2),
            }
        )
    results.sort(key=lambda r: r["relevance"], reverse=True)

    info = start_indexing(jobs)  # kicks off background indexing if jobs are missing
    return {
        "query": query,
        "company": None,
        "total_matches": len(results),
        "results": results[:limit],
        "semantic": {
            "indexed": info["indexed"],
            "total": info["total"],
            "indexing": info["running"],
            "error": sem_error or info["error"],
        },
    }