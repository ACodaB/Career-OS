"""
Per-job application documents (PDFs).

Each job gets its own folder:
    backend/data/applications/job<ID>_<company>_<title>/
        <Name>_Resume.pdf          tailored resume (formatted like the base resume)
        <Name>_Cover_Letter.pdf    tailored cover letter

File names use your name because recruiters see them on the application form.
"""
import html as _html
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from app.services.resume_render import build_resume_html

BACKEND_DIR = Path(__file__).resolve().parents[2]  # .../backend
DATA_DIR = BACKEND_DIR / "data"
APPLICATIONS_DIR = DATA_DIR / "applications"
DEFAULTS_PATH = DATA_DIR / "autofill_defaults.json"


def _slug(text: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:maxlen].strip("-") or "x"


def _person(profile) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", (profile.name or "").strip()).strip("_")
    return s or "Candidate"


def job_folder(job, create: bool = True) -> Path:
    folder = APPLICATIONS_DIR / f"job{job.id}_{_slug(job.company, 20)}_{_slug(job.title)}"
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def resume_pdf_path(job, profile, create: bool = False) -> Path:
    return job_folder(job, create=create) / f"{_person(profile)}_Resume.pdf"


def cover_letter_pdf_path(job, profile, create: bool = False) -> Path:
    return job_folder(job, create=create) / f"{_person(profile)}_Cover_Letter.pdf"


def load_defaults() -> dict:
    if DEFAULTS_PATH.exists():
        return json.loads(DEFAULTS_PATH.read_text(encoding="utf-8"))
    return {}


def render_pdf(html_text: str, out_path: Path) -> Path:
    """HTML string -> PDF file, via the pdf_render subprocess."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_html = out_path.with_suffix(".html")
    tmp_html.write_text(html_text, encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, "-u", "-m", "app.services.pdf_render", str(tmp_html), str(out_path)],
            cwd=str(BACKEND_DIR),
            capture_output=True,
            text=True,
            timeout=90,
        )
    finally:
        tmp_html.unlink(missing_ok=True)
    if proc.returncode != 0 or not out_path.exists():
        tail = (proc.stderr or proc.stdout or "")[-500:]
        raise RuntimeError(f"PDF render failed (exit {proc.returncode}): {tail}")
    return out_path


# ---------------------------------------------------------------- resume ----
def build_resume_pdf(job, profile, resume_text: str | None = None) -> Path:
    """
    Render the tailored resume to this job's folder. `resume_text` overrides the
    saved version (used when you've edited it in the app but not saved).
    The base LaTeX resume (profile.resume_text) supplies the hyperlinks.
    """
    markup = (resume_text if resume_text is not None else job.tailored_resume or "").strip()
    if not markup:
        raise ValueError("No tailored resume yet. Click Generate Application on this job first.")
    html_text = build_resume_html(profile, load_defaults(), profile.resume_text or "", markup)
    return render_pdf(html_text, resume_pdf_path(job, profile, create=True))


# ----------------------------------------------------------- cover letter ----
_LETTER_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Cover Letter</title>
<style>
  @page { size: A4; margin: 0.9in 1in; }
  body { font-family: "Latin Modern Roman", "LM Roman 10", "CMU Serif",
                      "Times New Roman", Georgia, serif;
         font-size: 11pt; line-height: 1.45; color: #111; }
  h1 { font-size: 18pt; margin: 0 0 3pt 0; font-weight: 700; letter-spacing: 0.3pt; }
  .contact { font-size: 10pt; color: #222; }
  a { color: inherit; text-decoration: none; }
  hr { border: 0; border-top: 0.5pt solid #000; margin: 9pt 0 14pt 0; }
  .date { margin-bottom: 14pt; }
  p { margin: 0 0 10pt 0; }
</style></head><body>
<h1>__NAME__</h1>
<div class="contact">__CONTACT__</div>
<hr>
<div class="date">__DATE__</div>
__BODY__
</body></html>"""


def build_cover_letter_html(profile, defaults: dict, body_text: str) -> str:
    esc = _html.escape
    contact = []
    if profile.email:
        contact.append(f'<a href="mailto:{esc(profile.email, quote=True)}">{esc(profile.email)}</a>')
    if profile.phone:
        contact.append(esc(profile.phone))
    for key, label in (("linkedin", "LinkedIn"), ("github", "GitHub"), ("website", "Website")):
        url = (defaults.get(key) or "").strip()
        if url:
            contact.append(f'<a href="{esc(url, quote=True)}">{label}</a>')

    text = body_text.replace("\\n", "\n").strip()  # guard against literal "\n"
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    body_html = "\n".join("<p>" + esc(p).replace("\n", "<br>") + "</p>" for p in paragraphs)

    now = datetime.now()
    return (
        _LETTER_TEMPLATE.replace("__NAME__", esc(profile.name or ""))
        .replace("__CONTACT__", " &nbsp;|&nbsp; ".join(contact))
        .replace("__DATE__", f"{now:%B} {now.day}, {now.year}")
        .replace("__BODY__", body_html)
    )


def build_cover_letter_pdf(job, profile, cover_text: str | None = None) -> Path:
    """Render the tailored cover letter. `cover_text` overrides the saved version."""
    text = (cover_text if cover_text is not None else job.tailored_cover_letter or "").strip()
    if not text:
        raise ValueError("No cover letter yet. Click Generate Application on this job first.")
    html_text = build_cover_letter_html(profile, load_defaults(), text)
    return render_pdf(html_text, cover_letter_pdf_path(job, profile, create=True))