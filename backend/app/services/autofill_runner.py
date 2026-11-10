"""
Standalone Playwright auto-fill runner (Greenhouse forms).

Run from the backend folder:
    python -m app.services.autofill_runner path/to/payload.json

Payload "mode":
    "scan" -> headless; only reads the form and reports the required essay
              questions. Fills nothing.
    "fill" -> (default) visible browser; fills what it can, including approved
              essay answers, then leaves the window open for you.

Payload keys:
    mode, url, first_name, last_name, email, phone,
    linkedin, github, website,
    resume_pdf_path, cover_letter_text,
    essay_answers   ({question text: answer text}),
    report_path

SAFETY: this script NEVER clicks Submit.
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.sync_api import sync_playwright


# ---------- low-level helpers ----------

def _read_value(loc) -> str:
    try:
        return loc.input_value(timeout=1500)
    except Exception:
        return ""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _same(read: str, expected: str) -> bool:
    """Tolerant compare: ignores spacing/punctuation, allows e.g. a +91 prefix on phones."""
    r, e = _norm(read), _norm(expected)
    return bool(r) and (r == e or e in r)


def _mark(report: dict, name: str, ok: bool) -> None:
    for key in ("filled", "not_filled"):
        if name in report[key]:
            report[key].remove(name)
    report["filled" if ok else "not_filled"].append(name)


# Why a field couldn't be filled (shown in the report so we can see the real reason)
_LAST_ERRORS: dict = {}


def _fill_by_label(scope, pattern: str, value) -> bool:
    """Fill the first matching field and VERIFY the value stuck."""
    if not value:
        return False
    value = str(value)
    try:
        loc = scope.get_by_label(re.compile(pattern, re.I)).first
        if loc.count() == 0:
            _LAST_ERRORS.pop(pattern, None)  # simply not on this form
            return False
        loc.scroll_into_view_if_needed(timeout=2000)
        loc.fill(value, timeout=3000)
        if _same(_read_value(loc), value):
            _LAST_ERRORS.pop(pattern, None)
            return True
        # The framework ignored the programmatic fill: type it like a person
        loc.click(timeout=2000)
        loc.press("Control+A")
        loc.press("Delete")
        loc.press_sequentially(value, delay=20)
        loc.press("Tab")  # blur so the form commits the value
        if _same(_read_value(loc), value):
            _LAST_ERRORS.pop(pattern, None)
            return True
        _LAST_ERRORS[pattern] = "typed it, but the page cleared or rejected the value"
        return False
    except Exception as e:
        _LAST_ERRORS[pattern] = f"{type(e).__name__}: {str(e).splitlines()[0][:140]}"
        return False

def _fill_essay(scope, question: str, answer: str) -> bool:
    """Fill the textarea whose label contains the essay question text."""
    if not answer:
        return False
    try:
        loc = scope.get_by_label(question, exact=False).first
        if loc.count() == 0:
            return False
        loc.scroll_into_view_if_needed(timeout=2000)
        loc.fill(answer, timeout=5000)
        return True
    except Exception:
        return False


def _upload_resume(page, scope, pdf_path: str) -> bool:
    if not pdf_path or not Path(pdf_path).exists():
        return False

    # 1) Preferred: click the real "Attach" button and answer the file dialog,
    #    so Greenhouse's own upload code runs (like a human would).
    try:
        btn = scope.get_by_role("button", name=re.compile(r"^\s*attach", re.I)).first
        if btn.count():
            with page.expect_file_chooser(timeout=5000) as fc_info:
                btn.click(timeout=3000)
            fc_info.value.set_files(pdf_path)
            page.wait_for_timeout(1500)
            return True
    except Exception:
        pass

    # 2) Fallback: set the hidden file input directly
    for selector in ("input[type='file']#resume", "input[type='file']"):
        try:
            loc = scope.locator(selector).first
            if loc.count() == 0:
                continue
            loc.set_input_files(pdf_path, timeout=5000)
            return True
        except Exception:
            continue
    return False

_ATTACH_RE = re.compile(r"^\s*attach", re.I)


def _upload_cover_letter_file(page, scope, pdf_path: str) -> bool:
    """Upload the job-specific cover letter PDF into the form's Cover Letter slot."""
    if not pdf_path or not Path(pdf_path).exists():
        return False
    # 1) Click the Attach button that sits in the "Cover Letter" block
    try:
        block = (
            scope.locator("div")
            .filter(has_text=re.compile(r"cover letter", re.I))
            .filter(has=scope.get_by_role("button", name=_ATTACH_RE))
            .last
        )
        if block.count():
            btn = block.get_by_role("button", name=_ATTACH_RE).first
            with page.expect_file_chooser(timeout=5000) as fc:
                btn.click(timeout=3000)
            fc.value.set_files(pdf_path)
            page.wait_for_timeout(1500)
            return True
    except Exception:
        pass
    # 2) Fallback: the cover letter's file input itself
    try:
        loc = scope.locator(
            "input[type='file']#cover_letter, input[type='file'][name*='cover' i]"
        ).first
        if loc.count():
            loc.set_input_files(pdf_path, timeout=5000)
            return True
    except Exception:
        pass
    return False

def _fill_cover_letter(scope, text: str) -> bool:
    if not text:
        return False
    # 1) A plain textarea is already on the page
    for selector in ("textarea#cover_letter_text", "textarea[name*='cover_letter']"):
        try:
            loc = scope.locator(selector).first
            if loc.count() and loc.is_visible():
                loc.fill(text, timeout=3000)
                return True
        except Exception:
            pass
    # 2) Old-style form: click "Enter manually" in the Cover Letter block, then fill
    try:
        block = scope.locator("div:has(> label:has-text('Cover Letter'))").first
        if block.count():
            block.get_by_role("button", name=re.compile("enter manually", re.I)).click(timeout=2000)
            block.locator("textarea").first.fill(text, timeout=3000)
            return True
    except Exception:
        pass
    return False


def _missing_required(scope) -> tuple[list[str], list[str]]:
    """
    Visible required fields that are still empty.
    Returns (essay_questions, other_fields). Essays = textareas;
    blank-label entries (dropdown search boxes) are dropped.
    """
    essays: list[str] = []
    others: list[str] = []
    try:
        els = scope.locator(
            "input[aria-required='true'], textarea[aria-required='true'], "
            "input[required], textarea[required]"
        )
        for i in range(els.count()):
            el = els.nth(i)
            try:
                t = (el.get_attribute("type") or "").lower()
                if t in ("file", "hidden", "checkbox", "radio"):
                    continue
                if not el.is_visible() or el.input_value():
                    continue
                tag = el.evaluate("e => e.tagName.toLowerCase()")
                label = el.evaluate(
                    "e => (e.labels && e.labels[0] ? e.labels[0].innerText : "
                    "(e.getAttribute('aria-label') || e.name || e.id))"
                )
                label = str(label).replace("*", "").strip()
                if not label:
                    continue
                target = essays if tag == "textarea" else others
                if label not in target:
                    target.append(label)
            except Exception:
                continue
    except Exception:
        pass
    return essays, others


# ---------- page / report helpers ----------

FIRST_NAME_RE = re.compile(r"^\s*first\s*name", re.I)

# ---------------------------------------------------------------------------
# Cookie popups
# ---------------------------------------------------------------------------
# Known cookie-vendor buttons (best effort; text/close/hide fallbacks follow).
_REJECT_SELECTORS = [
    "#onetrust-reject-all-handler",
    "#CybotCookiebotDialogBodyButtonDecline",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinDeclineAll",
    "#didomi-notice-disagree-button",
    "[data-testid='uc-deny-all-button']",
    "button.cky-btn-reject",
    ".osano-cm-denyAll",
    "[data-tid='banner-decline']",
    ".iubenda-cs-reject-btn",
    "#truste-consent-required",
    ".cmplz-deny",
    ".cm-btn-decline",
]
_ACCEPT_SELECTORS = [
    "#onetrust-accept-btn-handler",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept",
    "#didomi-notice-agree-button",
    "[data-testid='uc-accept-all-button']",
    "button.cky-btn-accept",
    ".osano-cm-accept-all",
    "[data-tid='banner-accept']",
    ".iubenda-cs-accept-btn",
    "#truste-consent-button",
    ".cmplz-accept",
    ".cm-btn-accept-all",
]
_REJECT_TEXT = re.compile(
    r"^\s*(reject( all)?( cookies)?|decline( all)?( cookies)?|deny( all)?( cookies)?"
    r"|refuse( all)?|disagree|no,? thanks|i decline|opt out( of all)?"
    r"|continue without (accepting|agreeing)"
    r"|(accept|allow|use|save) ?(only )?(the )?(necessary|essential|required)( cookies)?( only)?"
    r"|only (the )?(necessary|essential|required)( cookies)?"
    r"|(necessary|essential|required) (cookies )?only)\s*$",
    re.I,
)
_ACCEPT_TEXT = re.compile(
    r"^\s*(accept( all)?( cookies)?|allow( all)?( cookies)?|i (agree|accept)"
    r"|agree( and close)?|got it|ok(ay)?|accept (&|and) close)\s*$",
    re.I,
)

# One script, three actions: "detect", "close" (click the popup's X), "hide".
_COOKIE_JS = r"""
(action) => {
  const KNOWN = '#onetrust-consent-sdk,#onetrust-banner-sdk,.onetrust-pc-dark-filter,'
    + '#CybotCookiebotDialog,#didomi-host,.cky-consent-container,.osano-cm-window,'
    + '#usercentrics-root,#truste-consent-track,.truste_overlay,.truste_box_overlay,'
    + '#cmpbox,#cmpbox2,[id*="cookie-banner" i],[class*="cookie-banner" i],'
    + '[id*="cookie-consent" i],[class*="cookie-consent" i]';
  const WORDS = /cookie|consent|gdpr|tracking technolog|privacy choices/i;

  const looksLikeBanner = (el) => {
    const tc = el.textContent || '';
    if (tc.length < 20 || tc.length > 3000 || !WORDS.test(tc)) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 100 || r.height < 30) return false;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    const t = el.innerText || '';
    if (t.length < 20 || t.length > 1500) return false;
    const dialogish = el.matches('dialog,[role="dialog"],[role="alertdialog"],[aria-modal="true"]');
    const floating = cs.position === 'fixed' || cs.position === 'sticky';
    return dialogish || floating;
  };

  const all = Array.from(document.querySelectorAll(
    'div,section,aside,dialog,form,[role="dialog"],[role="alertdialog"]'));
  const matches = all.filter(looksLikeBanner);
  // keep only the innermost matches (the popup itself, not its page wrapper)
  const banners = matches.filter(el => !matches.some(o => o !== el && el.contains(o)));
  const knownVisible = Array.from(document.querySelectorAll(KNOWN)).filter(e => {
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  });

  if (action === 'detect') return banners.length > 0 || knownVisible.length > 0;

  if (action === 'hide') {
    knownVisible.forEach(e => e.style.setProperty('display', 'none', 'important'));
    banners.forEach(e => e.style.setProperty('display', 'none', 'important'));
    [document.documentElement, document.body].forEach(e =>
      e && e.style.setProperty('overflow', 'auto', 'important'));
    return true;
  }

  // action === 'close'
  const labels = (b) => [
    b.getAttribute('aria-label'), b.getAttribute('title'),
    b.innerText, (b.querySelector('svg title') || {}).textContent
  ].map(s => (s || '').replace(/\s+/g, ' ').trim()).filter(Boolean);
  const closeRe = /^(x|\u00d7|\u2715|\u2716|close|dismiss|close (banner|dialog|notice|message|popup|modal|cookie.*))$/i;

  for (const el of banners) {
    const br = el.getBoundingClientRect();
    for (const scope of [el, el.parentElement]) {
      if (!scope) continue;
      const btns = Array.from(scope.querySelectorAll('button,[role="button"]'));
      let hit = btns.find(b => labels(b).some(l => closeRe.test(l))
        || /\b(close|dismiss)\b/i.test(b.getAttribute('aria-label') || ''));
      if (!hit) {  // unlabelled icon button in the popup's top-right corner
        hit = btns.find(b => {
          if (labels(b).length > 0) return false;
          const r = b.getBoundingClientRect();
          return r.width > 0 && r.width < 80 && r.height < 80
            && r.right >= br.right - 90 && r.top <= br.top + 90;
        });
      }
      if (hit) { hit.click(); return true; }
    }
  }
  return false;
}
"""


def _click_first_visible(loc, limit: int = 6) -> bool:
    try:
        n = min(loc.count(), limit)
    except Exception:
        return False
    for i in range(n):
        el = loc.nth(i)
        try:
            if el.is_visible():
                el.click(timeout=3000)
                return True
        except Exception:
            continue
    return False


def _dismiss_cookie_banner(page, choice: str = "reject"):
    """
    Clear a cookie popup so it can't block clicks. Returns a short label of
    how it was handled, or None if no popup was found.
    choice="reject" (default) declines non-essential cookies;
    choice="accept" accepts them. It never opens a settings panel.
    """
    accept = choice == "accept"
    selectors = _ACCEPT_SELECTORS if accept else _REJECT_SELECTORS
    text = _ACCEPT_TEXT if accept else _REJECT_TEXT

    for _ in range(3):  # popups often appear a moment after page load
        frames = [f for f in page.frames if "greenhouse.io" not in (f.url or "")]
        for fr in frames:
            try:
                for sel in selectors:
                    if _click_first_visible(fr.locator(sel)):
                        page.wait_for_timeout(600)
                        return "known button"
                for role in ("button", "link"):
                    if _click_first_visible(fr.get_by_role(role, name=text)):
                        page.wait_for_timeout(600)
                        return "text button"
            except Exception:
                continue
        try:
            if page.evaluate(_COOKIE_JS, "close"):
                page.wait_for_timeout(600)
                return "close (X) button"
        except Exception:
            pass
        page.wait_for_timeout(700)

    # Nothing clickable worked. If a popup is still showing, get it out of the way.
    try:
        if page.evaluate(_COOKIE_JS, "detect"):
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
            if page.evaluate(_COOKIE_JS, "detect"):
                page.evaluate(_COOKIE_JS, "hide")
                return "hidden"
            return "escape key"
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Closed / removed postings
# ---------------------------------------------------------------------------
_DEAD_TEXT = re.compile(
    r"no longer (open|available|accepting)"
    r"|(position|job|role|posting) (has been|is|was) (filled|closed|removed)"
    r"|job (not found|has expired|is closed)"
    r"|(couldn.t|could not|can.t|cannot) find (that|this|the) (job|page|position)"
    r"|this (job|position|role) (has )?(expired|closed)",
    re.I,
)


def _closed_reason(page, response):
    """Why this posting looks closed/removed, or None. Only call when no form was found."""
    try:
        if response is not None and response.status in (404, 410):
            return f"HTTP {response.status}"
    except Exception:
        pass
    if "error=true" in (page.url or ""):
        return "redirected to an error page"
    for fr in page.frames:
        try:
            body = fr.locator("body").inner_text(timeout=2000)
        except Exception:
            continue
        m = _DEAD_TEXT.search(body or "")
        if m:
            return f'page says "{m.group(0)}"'
    return None


# ---------------------------------------------------------------------------
# Finding / opening the form
# ---------------------------------------------------------------------------
def _has_form(scope, timeout_ms: int = 3000) -> bool:
    """True if a 'First Name' field shows up in this page/frame."""
    try:
        scope.get_by_label(FIRST_NAME_RE).first.wait_for(state="visible", timeout=timeout_ms) #earlier state was attached
        return True
    except Exception:
        return False


def _find_form_scope(page, attempts: int = 3):
    """
    Locate the application form: inside a Greenhouse iframe (company career
    sites), or directly on the page. Retries because embedded forms can load
    a few seconds after the page. Returns the scope, or None.
    """
    for _ in range(attempts):
        candidates = []
        for sel in ("iframe#grnhse_iframe", "iframe[src*='greenhouse.io']"):
            try:
                if page.locator(sel).count():
                    candidates.append(page.frame_locator(sel).first)
            except Exception:
                pass
        candidates.append(page)  # form directly on the page

        for scope in candidates:
            if _has_form(scope):
                return scope
        page.wait_for_timeout(1000)
    return None


def _wait_settled(page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(1500)


_APPLY_RE = re.compile(r"^\s*apply\b[^\n]{0,25}$", re.I)
_APPLICATION_RE = re.compile(r"^\s*(job )?application\s*$", re.I)


def _visible_matches(loc, limit: int = 4):
    out = []
    try:
        n = min(loc.count(), limit * 3)
    except Exception:
        return out
    for i in range(n):
        el = loc.nth(i)
        try:
            if el.is_visible():
                out.append(el)
        except Exception:
            continue
        if len(out) >= limit:
            break
    return out


def _activate(page, el) -> None:
    """Follow a link's href in this tab (avoids new-tab links), else click it."""
    href = None
    try:
        href = el.get_attribute("href", timeout=1000)
    except Exception:
        pass
    if href and not href.startswith("#") and not href.lower().startswith("javascript"):
        page.goto(urljoin(page.url, href), wait_until="domcontentloaded", timeout=45000)
        return
    try:
        el.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass
    try:
        el.click(timeout=3000)
    except Exception:
        el.evaluate("e => e.click()")  # covered by an overlay? click via JS


def _click_through_to_form(page, cookie_choice: str):
    """
    Click 'Apply' / 'Application' (any element type, matched by its text)
    until the form shows up. Returns the form scope, or None.
    """
    start_url = page.url
    groups = [
        page.get_by_role("link", name=_APPLY_RE),
        page.get_by_role("button", name=_APPLY_RE),
        page.get_by_text(_APPLY_RE),
        page.get_by_role("tab", name=_APPLICATION_RE),
        page.get_by_role("link", name=_APPLICATION_RE),
        page.get_by_text(_APPLICATION_RE),
    ]
    tried = 0
    for loc in groups:
        for el in _visible_matches(loc):
            if tried >= 6:
                return None
            tried += 1
            try:
                _activate(page, el)
            except Exception:
                continue
            page.wait_for_timeout(1500)
            try:
                if page.evaluate(_COOKIE_JS, "detect"):
                    how = _dismiss_cookie_banner(page, cookie_choice)
                    if how:
                        print(f"[autofill] cookie popup handled: {how}")
            except Exception:
                pass
            scope = _find_form_scope(page, attempts=1)
            if scope is not None:
                print(f"[autofill] form reached after clicking: {tried} attempt(s)")
                return scope
            if page.url != start_url:
                return None  # we landed on some other page; stop clicking around
    return None


def _greenhouse_embed_url(job_url: str, board_token, page):
    """The standard Greenhouse form URL, built from the job id and board token."""
    parsed = urlparse(job_url)
    jid = (parse_qs(parsed.query).get("gh_jid") or [None])[0]
    if not jid:
        m = re.search(r"/(\d{7,})(?:/|$)", parsed.path)
        jid = m.group(1) if m else None

    token = ""
    try:  # the page itself is the most reliable source for the board token
        m = re.search(r"greenhouse\.io/embed/job_app\?for=([A-Za-z0-9_-]+)", page.content())
        token = m.group(1) if m else ""
    except Exception:
        pass
    if not token:
        token = (board_token or "").strip().lower()

    if not (jid and token):
        return None
    return f"https://job-boards.greenhouse.io/embed/job_app?for={token}&token={jid}"


def _open_greenhouse_embed(page, job_url: str, board_token):
    embed = _greenhouse_embed_url(job_url, board_token, page)
    if not embed:
        return None
    try:
        page.goto(embed, wait_until="domcontentloaded", timeout=45000)
        _wait_settled(page)
    except Exception:
        return None
    print(f"[autofill] opened Greenhouse form directly: {embed}")
    return _find_form_scope(page)


_DIAG_JS = r"""
() => {
  const out = [];
  const re = /apply|application/i;
  document.querySelectorAll('a,button,[role],li,div,span,p,h2,h3').forEach(e => {
    const t = (e.innerText || '').replace(/\s+/g, ' ').trim();
    if (!t || t.length > 40 || !re.test(t) || e.children.length > 3) return;
    const r = e.getBoundingClientRect();
    out.push({tag: e.tagName.toLowerCase(), role: e.getAttribute('role'), text: t,
              href: e.getAttribute('href'), visible: r.width > 0 && r.height > 0});
  });
  return out.slice(0, 20);
}
"""


def _page_diagnostics(page) -> dict:
    """What's on the page when no form was found, so we can see why."""
    info = {"page_url": page.url, "iframes": [], "apply_candidates": []}
    try:
        info["iframes"] = [f.url for f in page.frames if f.url and f.url != "about:blank"]
    except Exception:
        pass
    try:
        info["apply_candidates"] = page.evaluate(_DIAG_JS)
    except Exception:
        pass
    return info


def _open_form(p, url: str, headless: bool, cookie_choice: str = "reject", board_token=None):
    """Returns (browser, page, scope, form_found, closed_reason)."""
    browser = p.chromium.launch(headless=headless)
    page = browser.new_page()
    response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
    _wait_settled(page)

    how = _dismiss_cookie_banner(page, cookie_choice)
    if how:
        print(f"[autofill] cookie popup handled: {how}")

    scope = _find_form_scope(page)
    closed = None
    if scope is None:
        # Is the posting dead? Check BEFORE clicking around.
        closed = _closed_reason(page, response)
    if scope is None and closed is None:
        scope = _click_through_to_form(page, cookie_choice)
        if scope is None:
            closed = _closed_reason(page, None)
    if scope is None and closed is None:
        # Clicking didn't work: open the standard Greenhouse form directly.
        # (No closed-check afterwards: a wrong guessed token looks like "not found".)
        scope = _open_greenhouse_embed(page, url, board_token)

    return browser, page, (scope if scope is not None else page), scope is not None, closed


def _write_report(report: dict, payload: dict) -> None:
    report["debug"] = {
        "json_file": payload.get("_json_path"),
        "payload_keys": sorted(k for k in payload if not k.startswith("_")),
        "essay_answers_received": len(payload.get("essay_answers") or {}),
    }
    report_path = payload.get("report_path")
    if report_path:
        Path(report_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


# ---------- the two modes ----------
def _name_field_debug(scope) -> list[dict]:
    """Every field with 'name' in its label, with its current value (for diagnosing)."""
    out = []
    try:
        els = scope.get_by_label(re.compile(r"name", re.I))
        for i in range(min(els.count(), 12)):
            el = els.nth(i)
            try:
                label = el.evaluate(
                    "e => (e.labels && e.labels[0] ? e.labels[0].innerText : "
                    "(e.getAttribute('aria-label') || e.name || e.id))"
                )
                out.append(
                    {
                        "label": str(label).replace("*", "").strip(),
                        "value": el.input_value(),
                        "visible": el.is_visible(),
                    }
                )
            except Exception:
                continue
    except Exception:
        pass
    return out

# ---------------------------------------------------------------------------
# Employment / education / location fields (text boxes AND dropdowns)
# ---------------------------------------------------------------------------
# (payload key, label regex, loose). `loose` lets month dropdowns match "Jul" for "July".
_EXTRA_FIELDS = [
    ("country", r"^\s*country\b|country where you currently reside", False),
    ("city", r"location \(city\)", False),
    ("zip", r"zip|postal", False),
    ("employer", r"^\s*company name\b|current or previous employer|^\s*employer\b", False),
    ("job_title", r"^\s*(job )?title\b|current or previous job title", False),
    ("start_month", r"start date.{0,3}month", True),
    ("start_year", r"start date.{0,3}year", False),
    ("end_month", r"end date.{0,3}month", True),
    ("end_year", r"end date.{0,3}year", False),
    ("school", r"^\s*school\b", False),
    ("degree", r"^\s*degree\b", False),
    ("discipline", r"^\s*(discipline|major|field of study)\b", False),
]


def _pick_native(loc, value: str, loose: bool = False) -> bool:
    """A real <select>: choose the option whose text matches."""
    try:
        options = [o.strip() for o in loc.locator("option").all_inner_texts()]
    except Exception:
        return False
    want = value.strip().lower()
    tiers = [
        lambda o: o.lower() == want,
        lambda o: re.match(rf"{re.escape(want)}\b", o.lower()) is not None,
        lambda o: want in o.lower(),
    ]
    if loose and len(want) > 3:
        tiers.append(lambda o: o.lower().startswith(want[:3]))
    for test in tiers:
        for opt in options:
            if opt and test(opt):
                try:
                    loc.select_option(label=opt, timeout=3000)
                    return True
                except Exception:
                    return False
    return False


def _option_for(scope, text: str):
    """Best dropdown option for `text`: exact, then starts-with, then contains."""
    esc = re.escape(text)
    for rx in (rf"^\s*{esc}\s*$", rf"^\s*{esc}\b", esc):
        opt = scope.get_by_role("option").filter(has_text=re.compile(rx, re.I)).first
        try:
            if opt.count():
                return opt
        except Exception:
            continue
    return None


def _pick_combobox(page, scope, loc, value: str, loose: bool = False) -> bool:
    """A searchable dropdown / autocomplete: type to filter, then click the matching option."""
    candidates = [value]
    if loose and len(value) > 3:
        candidates.append(value[:3])
    for text in candidates:
        try:
            loc.click(timeout=3000)
            loc.press("Control+A")
            loc.press("Delete")
            loc.press_sequentially(text, delay=40)
            page.wait_for_timeout(900)
            opt = _option_for(scope, text)
            if opt is not None:
                opt.click(timeout=3000)
                page.wait_for_timeout(300)
                return True
        except Exception:
            pass
        try:  # nothing matched: clear what we typed and close the list
            loc.press("Escape")
            loc.press("Control+A")
            loc.press("Delete")
        except Exception:
            pass
    return False


def _fill_any(page, scope, pattern: str, value: str, loose: bool = False) -> str:
    """
    Fill a text box, a native <select>, or a searchable dropdown.
    Returns "filled" | "selected" | "failed" | "absent".
    """
    if not value:
        return "absent"
    try:
        loc = scope.get_by_label(re.compile(pattern, re.I)).first
        if loc.count() == 0:
            return "absent"
        loc.scroll_into_view_if_needed(timeout=2000)
        tag = loc.evaluate("e => e.tagName.toLowerCase()")
        role = (loc.get_attribute("role") or "").lower()
        if tag == "select":
            return "selected" if _pick_native(loc, value, loose) else "failed"
        if role == "combobox" or loc.get_attribute("aria-haspopup") or loc.get_attribute("aria-autocomplete"):
            return "selected" if _pick_combobox(page, scope, loc, value, loose) else "failed"
        return "filled" if _fill_by_label(scope, pattern, value) else "failed"
    except Exception:
        return "failed"


def _settle_after_upload(page, scope) -> None:
    """
    Forms often parse an uploaded resume and rewrite their own fields. Wait for
    the page to go quiet and the first-name box to be editable before typing.
    """
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    for _ in range(20):
        try:
            box = scope.get_by_label(FIRST_NAME_RE).first
            if box.count() and box.is_editable():
                break
        except Exception:
            pass
        page.wait_for_timeout(500)
    page.wait_for_timeout(2000)


def _verify_and_repair(page, scope, text_fields, report) -> None:
    """
    Page scripts can wipe fields after we typed them. Re-check every value and
    retype anything missing, until everything has stayed put for two rounds in a row.
    """
    stable = 0
    for _ in range(6):
        page.wait_for_timeout(1500)
        missing = []
        for name, pattern, value in text_fields:
            if not value:
                continue
            try:
                loc = scope.get_by_label(re.compile(pattern, re.I)).first
                if loc.count() == 0:
                    continue  # this form doesn't have that field
                if _same(_read_value(loc), value):
                    continue
            except Exception:
                pass
            missing.append((name, pattern, value))
        if not missing:
            stable += 1
            if stable >= 2:
                return
            continue
        stable = 0
        for name, pattern, value in missing:
            _mark(report, name, _fill_by_label(scope, pattern, value))


def scan(payload: dict) -> dict:
    """Headless: read the form, report required essay questions. Fills nothing."""
    report = {"mode": "scan", "url": payload["url"], "essay_questions": []}
    print("[autofill] scan: launching browser", flush=True)
    with sync_playwright() as p:
        browser, page, scope, form_found, closed = _open_form(
            p,
            payload["url"],
            headless=True,
            cookie_choice=payload.get("cookie_choice", "reject"),
            board_token=payload.get("board_token"),
        )
        print(
            f"[autofill] scan: form_found={form_found} closed={closed} url={page.url}",
            flush=True,
        )
        report["form_found"] = form_found
        report["final_url"] = page.url
        if closed:
            report["job_closed"] = True
            report["closed_reason"] = closed
        elif form_found:
            report["essay_questions"], _ = _missing_required(scope)
        else:
            report["diagnostics"] = _page_diagnostics(page)
            if payload.get("report_path"):
                page.screenshot(path=str(Path(payload["report_path"]).with_suffix(".png")))
        browser.close()
    _write_report(report, payload)
    print(f"[autofill] scan: done, report file exists: {Path(payload.get('report_path', '')).exists()}", flush=True)
    return report


def fill(payload: dict) -> dict:
    """Visible browser: fill everything we can, then leave it open for review."""
    report = {
        "mode": "fill",
        "url": payload["url"],
        "filled": [],
        "not_filled": [],
        "essays_filled": [],
        "essays_not_filled": [],
        "essay_questions": [],
        "needs_you": [],
    }

    with sync_playwright() as p:
        browser, page, scope, form_found, closed = _open_form(
            p,
            payload["url"],
            headless=False,
            cookie_choice=payload.get("cookie_choice", "reject"),
            board_token=payload.get("board_token"),
        )
        report["form_found"] = form_found
        report["final_url"] = page.url
        if closed:
            report["job_closed"] = True
            report["closed_reason"] = closed
            _write_report(report, payload)
            browser.close()
            return report
        if not form_found:
            report["diagnostics"] = _page_diagnostics(page)

        text_fields = [
            ("first_name", r"^\s*first\s*name", payload.get("first_name")),
            ("last_name", r"^\s*last\s*name", payload.get("last_name")),
            ("email", r"^\s*email", payload.get("email")),
            ("phone", r"^\s*phone", payload.get("phone")),
            ("linkedin", r"linkedin", payload.get("linkedin")),
            ("github", r"github", payload.get("github")),
            ("website", r"website|portfolio", payload.get("website")),
        ]

        # 1) Resume first: some forms parse it and re-render/overwrite fields afterwards
        ok = _upload_resume(page, scope, payload.get("resume_pdf_path", ""))
        _mark(report, "resume_upload", ok)
        _settle_after_upload(page, scope)

        # 2) Text fields (each one verified after typing)
        for name, pattern, value in text_fields:
            _mark(report, name, _fill_by_label(scope, pattern, value))

        # 3) Cover letter: upload this job's PDF if the form takes a file, else paste the text
        ok = _upload_cover_letter_file(page, scope, payload.get("cover_letter_pdf_path", ""))
        if not ok:
            ok = _fill_cover_letter(scope, payload.get("cover_letter_text", ""))
        _mark(report, "cover_letter", ok)

        # 4) Essay answers
        for question, answer in (payload.get("essay_answers") or {}).items():
            ok = _fill_essay(scope, question, answer)
            (report["essays_filled"] if ok else report["essays_not_filled"]).append(question)

        # 4b) Employment / education / location (text boxes and dropdowns)
        report["extras_filled"], report["extras_failed"] = [], []
        done_patterns = []
        extras = payload.get("extras") or {}
        for key, pattern, loose in _EXTRA_FIELDS:
            value = extras.get(key)
            if not value:
                continue
            result = _fill_any(page, scope, pattern, str(value), loose)
            if result in ("filled", "selected"):
                report["extras_filled"].append(key)
                done_patterns.append(pattern)
            elif result == "failed":
                report["extras_failed"].append(key)
            # "absent" just means this form doesn't have that field
        # 5) Verify + repair: the page can wipe fields after we typed them
        _verify_and_repair(page, scope, text_fields, report)
        report["fill_errors"] = {
            name: _LAST_ERRORS[pattern]
            for name, pattern, value in text_fields
            if value and name in report["not_filled"] and pattern in _LAST_ERRORS
        }
        report["debug_name_fields"] = _name_field_debug(scope)

        # Whatever is still empty after filling
        report["essay_questions"], needs = _missing_required(scope)
        report["needs_you"] = [
            x for x in needs if not any(re.search(p, x, re.I) for p in done_patterns)
        ]

        # Write the report BEFORE waiting, so the backend can read it right away
        _write_report(report, payload)

        # Leave the window open for manual review. NEVER auto-submit.
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass
        browser.close()

    return report


def run(payload: dict) -> dict:
    mode = (payload.get("mode") or "fill").lower()
    print(f"[autofill] mode={mode}, essay_answers={len(payload.get('essay_answers') or {})}")
    if mode == "scan":
        return scan(payload)
    return fill(payload)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m app.services.autofill_runner payload.json")
        sys.exit(1)

    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    payload["_json_path"] = str(Path(sys.argv[1]).resolve())

    # Remove any stale report so you never mistake an old one for a new one
    rp = payload.get("report_path")
    if rp and Path(rp).exists():
        Path(rp).unlink()

    try:
        run(payload)
    except Exception:
        import traceback

        err = traceback.format_exc()
        print(err, file=sys.stderr, flush=True)
        if rp:
            Path(rp).write_text(
                json.dumps(
                    {"mode": payload.get("mode"), "url": payload.get("url"), "error": err[-1500:]},
                    indent=2,
                ),
                encoding="utf-8",
            )
        sys.exit(1)